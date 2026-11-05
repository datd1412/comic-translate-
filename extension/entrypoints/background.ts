import { defineBackground } from "wxt/sandbox";
import { MAX_CUSTOM_CONTEXT_LENGTH } from "../src/core/adapters";

export interface UserInfoPayload {
  email?: string;
  name?: string;
  tier?: string;
  email_verified?: boolean;
  credits?: {
    subscription: number;
    one_time: number;
    total: number;
  };
  monthly_credits?: number;
  avatar_url?: string;
}

export interface StoredExtensionState {
  serverUrl: string;
  accessToken: string;
  refreshToken: string;
  userInfo: UserInfoPayload | null;
  enabled: boolean;
  debugSelectorMode: boolean;
  customSelectors: Record<string, string>;
  customContext: string;
}

const DEFAULT_STATE: StoredExtensionState = {
  serverUrl: "http://127.0.0.1:8000",
  accessToken: "",
  refreshToken: "",
  userInfo: null,
  enabled: true,
  debugSelectorMode: false,
  customSelectors: {},
  customContext: "",
};

async function getState(): Promise<StoredExtensionState> {
  const raw = await chrome.storage.local.get(Object.keys(DEFAULT_STATE));
  return {
    serverUrl: (raw.serverUrl as string) || DEFAULT_STATE.serverUrl,
    accessToken: (raw.accessToken as string) || "",
    refreshToken: (raw.refreshToken as string) || "",
    userInfo: (raw.userInfo as StoredExtensionState["userInfo"]) || null,
    enabled: typeof raw.enabled === "boolean" ? raw.enabled : true,
    debugSelectorMode:
      typeof raw.debugSelectorMode === "boolean" ? raw.debugSelectorMode : false,
    customSelectors:
      (raw.customSelectors as Record<string, string>) || {},
    customContext: ((raw.customContext as string) || "").slice(
      0,
      MAX_CUSTOM_CONTEXT_LENGTH
    ),
  };
}

async function setState(
  patch: Partial<StoredExtensionState>
): Promise<StoredExtensionState> {
  if (typeof patch.customContext === "string") {
    patch.customContext = patch.customContext.slice(
      0,
      MAX_CUSTOM_CONTEXT_LENGTH
    );
  }
  await chrome.storage.local.set(patch);
  return getState();
}

/**
 * Cấu hình quy tắc declarativeNetRequest động để gán Referer và Origin
 * khi tải ảnh từ CDN có kiểm tra chống hotlink (baozimh.org / hivetoons.org).
 */
async function ensureHotlinkRefererRule(
  imageUrl: string,
  refererOrigin: string
): Promise<void> {
  if (!chrome.declarativeNetRequest?.updateSessionRules) {
    return;
  }
  try {
    const parsedImg = new URL(imageUrl);
    if (parsedImg.protocol !== "http:" && parsedImg.protocol !== "https:") {
      return;
    }
    const parsedRef = new URL(refererOrigin);
    const ruleId = 9001;
    await chrome.declarativeNetRequest.updateSessionRules({
      removeRuleIds: [ruleId],
      addRules: [
        {
          id: ruleId,
          priority: 1,
          action: {
            type: chrome.declarativeNetRequest.RuleActionType.MODIFY_HEADERS,
            requestHeaders: [
              {
                header: "Referer",
                operation: chrome.declarativeNetRequest.HeaderOperation.SET,
                value: parsedRef.href,
              },
              {
                header: "Origin",
                operation: chrome.declarativeNetRequest.HeaderOperation.SET,
                value: parsedRef.origin,
              },
            ],
          },
          condition: {
            urlFilter: `||${parsedImg.hostname}/`,
            resourceTypes: [
              chrome.declarativeNetRequest.ResourceType.XMLHTTPREQUEST,
              chrome.declarativeNetRequest.ResourceType.IMAGE,
            ],
          },
        },
      ],
    });
  } catch {
    // Bỏ qua nếu URL là data: hoặc blob:
  }
}

function dataUrlToBlob(dataUrl: string): Blob {
  const parts = dataUrl.split(",");
  const meta = parts[0] || "";
  const base64 = parts[1] || "";
  const mimeMatch = meta.match(/data:([^;]+);base64/i);
  const mime = mimeMatch ? mimeMatch[1] : "image/png";
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type: mime });
}

async function fetchImageBlobInBackground(
  imageUrl: string,
  imageDataUrl: string | undefined,
  refererOrigin: string
): Promise<Blob> {
  if (imageDataUrl && imageDataUrl.startsWith("data:")) {
    return dataUrlToBlob(imageDataUrl);
  }
  if (imageUrl.startsWith("data:")) {
    return dataUrlToBlob(imageUrl);
  }

  await ensureHotlinkRefererRule(imageUrl, refererOrigin);
  const resp = await fetch(imageUrl, {
    method: "GET",
    credentials: "omit",
  });
  if (!resp.ok) {
    throw new Error(`Không thể tải ảnh từ CDN (HTTP ${resp.status})`);
  }
  return await resp.blob();
}

/**
 * Tự động gọi `/auth/v1/refresh` bằng `refresh_token` khi access token hết hạn (HTTP 401).
 */
async function refreshAccessTokenIfPossible(
  serverUrl: string,
  refreshToken: string
): Promise<string | null> {
  if (!refreshToken) {
    return null;
  }
  const resp = await fetch(`${serverUrl.replace(/\/$/, "")}/auth/v1/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!resp.ok) {
    return null;
  }
  const data = await resp.json();
  const newAccess = (data.access_token || "").trim();
  const newRefresh = (data.refresh_token || refreshToken).trim();
  if (!newAccess) {
    return null;
  }
  await setState({
    accessToken: newAccess,
    refreshToken: newRefresh,
  });
  return newAccess;
}

/**
 * Gọi `GET /auth/v1/user_info` để đồng bộ `userInfo` và số dư `credits` thực tế vào `chrome.storage.local`.
 * Nếu gặp HTTP 401 và có `refreshToken`, tự động làm mới token rồi thử lại.
 */
async function syncUserInfoFromServer(): Promise<{
  ok: boolean;
  state: StoredExtensionState;
  error?: string;
}> {
  let state = await getState();
  const serverUrl = state.serverUrl.replace(/\/$/, "");
  let accessToken = state.accessToken.trim();

  if (!accessToken) {
    state = await setState({ userInfo: null });
    return { ok: false, state, error: "Chưa có accessToken." };
  }

  const doFetchUserInfo = async (token: string): Promise<Response> => {
    return fetch(`${serverUrl}/auth/v1/user_info`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
      },
    });
  };

  try {
    let resp = await doFetchUserInfo(accessToken);
    if (resp.status === 401 && state.refreshToken) {
      const refreshed = await refreshAccessTokenIfPossible(
        serverUrl,
        state.refreshToken
      );
      if (refreshed) {
        accessToken = refreshed;
        resp = await doFetchUserInfo(accessToken);
      }
    }

    if (!resp.ok) {
      return {
        ok: false,
        state: await getState(),
        error: `Không thể lấy user_info (HTTP ${resp.status})`,
      };
    }

    const data = (await resp.json()) as UserInfoPayload;
    const normalizedUserInfo: UserInfoPayload = {
      email: data.email || "",
      name: data.name || "",
      tier: data.tier || "Free",
      email_verified: Boolean(data.email_verified),
      credits: {
        subscription: Number(data.credits?.subscription ?? 0),
        one_time: Number(data.credits?.one_time ?? 0),
        total: Number(
          data.credits?.total ??
            Number(data.credits?.subscription ?? 0) +
              Number(data.credits?.one_time ?? 0)
        ),
      },
      monthly_credits: Number(data.monthly_credits ?? 0),
      avatar_url: data.avatar_url || "",
    };

    const updatedState = await setState({ userInfo: normalizedUserInfo });
    return { ok: true, state: updatedState };
  } catch (err) {
    return {
      ok: false,
      state: await getState(),
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

async function handleTranslatePageRequest(payload: {
  imageUrl: string;
  imageDataUrl?: string;
  langPair: string;
  idempotencyKey: string;
  refererOrigin: string;
  readingDirection?: "rtl" | "ltr";
  context?: Record<string, unknown>;
}) {
  const state = await getState();
  const serverUrl = state.serverUrl.replace(/\/$/, "");
  let accessToken = state.accessToken;

  const imgBlob = await fetchImageBlobInBackground(
    payload.imageUrl,
    payload.imageDataUrl,
    payload.refererOrigin || "https://www.baozimh.org/"
  );

  // Đóng gói custom_context từ state hoặc payload.context mà không phát sinh thêm API call
  const mergedContext: Record<string, unknown> = {
    ...(payload.context || {}),
  };
  if (
    typeof mergedContext.custom_context !== "string" ||
    !mergedContext.custom_context.trim()
  ) {
    if (state.customContext.trim()) {
      mergedContext.custom_context = state.customContext
        .trim()
        .slice(0, MAX_CUSTOM_CONTEXT_LENGTH);
    }
  } else {
    mergedContext.custom_context = String(mergedContext.custom_context)
      .trim()
      .slice(0, MAX_CUSTOM_CONTEXT_LENGTH);
  }

  const sendTranslateHttp = async (tokenToUse: string): Promise<Response> => {
    const form = new FormData();
    form.append("image", imgBlob, "page.png");
    form.append("lang_pair", payload.langPair);
    form.append("idempotency_key", payload.idempotencyKey);
    if (payload.readingDirection) {
      form.append("reading_direction", payload.readingDirection);
    }
    form.append("context_json", JSON.stringify(mergedContext));

    const headers: Record<string, string> = {};
    if (tokenToUse) {
      headers["Authorization"] = `Bearer ${tokenToUse}`;
    }
    return fetch(`${serverUrl}/api/v1/page/translate`, {
      method: "POST",
      headers,
      body: form,
    });
  };

  let resp = await sendTranslateHttp(accessToken);

  // Tự động refresh token khi gặp HTTP 401 và thử lại đúng 1 lần
  if (resp.status === 401 && state.refreshToken) {
    const refreshedToken = await refreshAccessTokenIfPossible(
      serverUrl,
      state.refreshToken
    );
    if (refreshedToken) {
      accessToken = refreshedToken;
      resp = await sendTranslateHttp(accessToken);
    }
  }

  let bodyJson: Record<string, unknown> = {};
  try {
    bodyJson = (await resp.json()) as Record<string, unknown>;
  } catch {
    bodyJson = {};
  }

  if (!resp.ok) {
    return {
      ok: false,
      status: resp.status,
      error:
        (bodyJson.detail as string) ||
        (bodyJson.error as string) ||
        `Lỗi dịch trang (HTTP ${resp.status})`,
    };
  }

  if (bodyJson.credits && typeof bodyJson.credits === "object") {
    const currentState = await getState();
    const currentInfo = currentState.userInfo || {};
    await setState({
      userInfo: {
        ...currentInfo,
        credits: bodyJson.credits as {
          subscription: number;
          one_time: number;
          total: number;
        },
      },
    });
  }

  return {
    ok: true,
    status: 200,
    data: bodyJson,
  };
}

async function syncFromCookies(serverUrl?: string): Promise<{
  ok: boolean;
  state: StoredExtensionState;
  synced?: boolean;
}> {
  const state = await getState();
  const urlToUse = (serverUrl || state.serverUrl || "http://127.0.0.1:8000").replace(/\/$/, "");

  if (!chrome.cookies?.get) {
    return { ok: false, state, synced: false };
  }

  try {
    const accessCookie = await chrome.cookies.get({
      url: urlToUse,
      name: "ct_access_token",
    });

    if (accessCookie && accessCookie.value) {
      const refreshCookie = await chrome.cookies.get({
        url: urlToUse,
        name: "ct_refresh_token",
      });

      await setState({
        accessToken: accessCookie.value,
        refreshToken: refreshCookie?.value || "",
      });

      const syncRes = await syncUserInfoFromServer();
      return { ok: true, state: syncRes.state, synced: true };
    }
  } catch (err) {
    console.warn("Lỗi đọc cookie từ server:", err);
  }

  return { ok: false, state, synced: false };
}

async function handleGoogleLoginFlow(): Promise<{
  ok: boolean;
  error?: string;
  state?: StoredExtensionState;
}> {
  const state = await getState();
  const serverUrl = state.serverUrl.replace(/\/$/, "");
  const extId = chrome.runtime.id;
  const redirectUri = `https://${extId}.chromiumapp.org/callback`;
  const authUrl = `${serverUrl}/login/?redirect_uri=${encodeURIComponent(redirectUri)}`;

  // 1. Kiểm tra nhanh xem trình duyệt đã đăng nhập trên Web chưa (qua cookies)
  const quickCookieCheck = await syncFromCookies(serverUrl);
  if (quickCookieCheck.ok && quickCookieCheck.state.accessToken) {
    return { ok: true, state: quickCookieCheck.state };
  }

  // 2. Mở tab bình thường để Google OAuth & Firebase hoạt động 100% không bị sandbox chặn
  const loginTab = await chrome.tabs.create({ url: authUrl, active: true });
  const targetTabId = loginTab.id;

  return new Promise((resolve) => {
    let resolved = false;

    // Lắng nghe navigation của Tab xem khi nào nó được redirect về callback của Extension
    const onUpdatedListener = async (
      tabId: number,
      changeInfo: chrome.tabs.TabChangeInfo,
      tab: chrome.tabs.Tab
    ) => {
      if (tabId !== targetTabId || resolved) return;

      const currentUrl = changeInfo.url || tab.url || "";
      if (currentUrl.includes(`${extId}.chromiumapp.org/callback`)) {
        resolved = true;
        chrome.tabs.onUpdated.removeListener(onUpdatedListener);
        chrome.tabs.onRemoved.removeListener(onRemovedListener);

        try {
          const parsed = new URL(currentUrl);
          const hashParams = new URLSearchParams(
            parsed.hash ? parsed.hash.slice(1) : ""
          );
          const accessToken =
            parsed.searchParams.get("access_token") ||
            hashParams.get("access_token") ||
            "";
          const refreshToken =
            parsed.searchParams.get("refresh_token") ||
            hashParams.get("refresh_token") ||
            "";

          // Đóng tab đăng nhập lại sau khi lấy xong token
          if (targetTabId) {
            try {
              await chrome.tabs.remove(targetTabId);
            } catch (_) {}
          }

          if (!accessToken) {
            const cookieFallback = await syncFromCookies(serverUrl);
            if (cookieFallback.ok && cookieFallback.state.accessToken) {
              resolve({ ok: true, state: cookieFallback.state });
              return;
            }
            resolve({
              ok: false,
              error: "Callback không chứa access_token.",
            });
            return;
          }

          await setState({ accessToken, refreshToken });
          const syncRes = await syncUserInfoFromServer();
          resolve({ ok: true, state: syncRes.state });
        } catch (err) {
          resolve({
            ok: false,
            error: `Lỗi đọc URL callback: ${String(err)}`,
          });
        }
      }
    };

    const onRemovedListener = async (tabId: number) => {
      if (tabId === targetTabId && !resolved) {
        resolved = true;
        chrome.tabs.onUpdated.removeListener(onUpdatedListener);
        chrome.tabs.onRemoved.removeListener(onRemovedListener);

        // Fallback kiểm tra cookies nếu người dùng đóng tab
        const cookieFallback = await syncFromCookies(serverUrl);
        if (cookieFallback.ok && cookieFallback.state.accessToken) {
          resolve({ ok: true, state: cookieFallback.state });
        } else {
          resolve({ ok: false, error: "Đã đóng tab đăng nhập." });
        }
      }
    };

    chrome.tabs.onUpdated.addListener(onUpdatedListener);
    chrome.tabs.onRemoved.addListener(onRemovedListener);
  });
}

export default defineBackground(() => {
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || typeof message !== "object") {
      return false;
    }

    if (message.type === "GET_STATE") {
      getState()
        .then((st) => sendResponse({ ok: true, state: st }))
        .catch((err) => sendResponse({ ok: false, error: String(err) }));
      return true;
    }

    if (message.type === "SET_CONFIG") {
      setState(message.patch || {})
        .then((st) => sendResponse({ ok: true, state: st }))
        .catch((err) => sendResponse({ ok: false, error: String(err) }));
      return true;
    }

    if (message.type === "SYNC_USER_INFO") {
      syncUserInfoFromServer()
        .then((res) => sendResponse(res))
        .catch((err) =>
          sendResponse({ ok: false, error: String(err) })
        );
      return true;
    }

    if (message.type === "SAVE_CUSTOM_SELECTOR") {
      getState()
        .then(async (st) => {
          const nextMap = {
            ...st.customSelectors,
            [String(message.hostname || "")]: String(message.selector || ""),
          };
          const updated = await setState({ customSelectors: nextMap });
          sendResponse({ ok: true, state: updated });
        })
        .catch((err) => sendResponse({ ok: false, error: String(err) }));
      return true;
    }

    if (message.type === "LOGIN_GOOGLE") {
      handleGoogleLoginFlow()
        .then((res) => sendResponse(res))
        .catch((err) => sendResponse({ ok: false, error: String(err) }));
      return true;
    }

    if (message.type === "SYNC_FROM_COOKIES") {
      syncFromCookies(message.serverUrl)
        .then((res) => sendResponse(res))
        .catch((err) => sendResponse({ ok: false, error: String(err) }));
      return true;
    }

    if (message.type === "LOGOUT") {
      getState().then(async (st) => {
        const cleanUrl = (st.serverUrl || "http://127.0.0.1:8000").replace(/\/$/, "");
        if (chrome.cookies?.remove) {
          try {
            await chrome.cookies.remove({ url: cleanUrl, name: "ct_access_token" });
            await chrome.cookies.remove({ url: cleanUrl, name: "ct_refresh_token" });
          } catch (_) {}
        }
        const updated = await setState({ accessToken: "", refreshToken: "", userInfo: null });
        sendResponse({ ok: true, state: updated });
      }).catch((err) => sendResponse({ ok: false, error: String(err) }));
      return true;
    }

    if (message.type === "TRANSLATE_PAGE") {
      handleTranslatePageRequest(message.payload)
        .then((res) => sendResponse(res))
        .catch((err) =>
          sendResponse({
            ok: false,
            status: 500,
            error: err instanceof Error ? err.message : String(err),
          })
        );
      return true;
    }

    return false;
  });
});
