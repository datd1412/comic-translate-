import {
  applyContextPreset,
  matchSiteAdapter,
  MAX_CUSTOM_CONTEXT_LENGTH,
  type ContextPresetChip,
} from "../../src/core/adapters";

const unsupportedBanner = document.getElementById(
  "unsupported-banner"
) as HTMLDivElement;
const requestSiteBtn = document.getElementById(
  "btn-request-site"
) as HTMLButtonElement;
const requestSiteMsg = document.getElementById(
  "request-site-msg"
) as HTMLDivElement;
const toggleEnabled = document.getElementById(
  "toggle-enabled"
) as HTMLInputElement;
const toggleDebugSelector = document.getElementById(
  "toggle-debug-selector"
) as HTMLInputElement;
const inputCustomContext = document.getElementById(
  "input-custom-context"
) as HTMLTextAreaElement;
const popupContextCounter = document.getElementById(
  "popup-context-counter"
) as HTMLSpanElement;
const authStatusBadge = document.getElementById(
  "auth-status-badge"
) as HTMLSpanElement;
const creditTotalEl = document.getElementById("credit-total") as HTMLElement;
const creditSubEl = document.getElementById("credit-sub") as HTMLElement;
const creditOneTimeEl = document.getElementById(
  "credit-onetime"
) as HTMLElement;
const googleLoginBtn = document.getElementById(
  "btn-google-login"
) as HTMLButtonElement;
const topupCreditBtn = document.getElementById(
  "btn-topup-credit"
) as HTMLButtonElement;
const inputServerUrl = document.getElementById(
  "input-server-url"
) as HTMLInputElement;
const inputAccessToken = document.getElementById(
  "input-access-token"
) as HTMLInputElement;
const inputRefreshToken = document.getElementById(
  "input-refresh-token"
) as HTMLInputElement;
const saveConfigBtn = document.getElementById(
  "btn-save-config"
) as HTMLButtonElement;

interface PopupStateView {
  serverUrl?: string;
  accessToken?: string;
  refreshToken?: string;
  enabled?: boolean;
  debugSelectorMode?: boolean;
  customContext?: string;
  userInfo?: {
    email?: string;
    name?: string;
    tier?: string;
    credits?: { subscription: number; one_time: number; total: number };
  } | null;
}

async function checkActiveTabSupport(): Promise<void> {
  const params = new URLSearchParams(window.location.search);
  const simulatedTabUrl = params.get("tabUrl");

  let activeUrl = simulatedTabUrl || "";
  if (!activeUrl && chrome.tabs?.query) {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    activeUrl = tabs[0]?.url || "";
  }

  const adapter = matchSiteAdapter(activeUrl);
  if (!adapter) {
    unsupportedBanner.style.display = "block";
  } else {
    unsupportedBanner.style.display = "none";
  }
}

function updateContextCounter(val: string): void {
  popupContextCounter.textContent = `${val.length}/${MAX_CUSTOM_CONTEXT_LENGTH}`;
}

function saveCustomContext(val: string): void {
  const trimmed = val.slice(0, MAX_CUSTOM_CONTEXT_LENGTH);
  inputCustomContext.value = trimmed;
  updateContextCounter(trimmed);
  chrome.runtime.sendMessage({
    type: "SET_CONFIG",
    patch: { customContext: trimmed },
  });
}

function renderState(state: PopupStateView): void {
  inputServerUrl.value = state.serverUrl || "http://127.0.0.1:8000";
  inputAccessToken.value = state.accessToken || "";
  inputRefreshToken.value = state.refreshToken || "";
  toggleEnabled.checked = state.enabled !== false;
  toggleDebugSelector.checked = Boolean(state.debugSelectorMode);

  const ctxVal = (state.customContext || "").slice(0, MAX_CUSTOM_CONTEXT_LENGTH);
  inputCustomContext.value = ctxVal;
  updateContextCounter(ctxVal);

  if (state.accessToken) {
    authStatusBadge.textContent = state.userInfo?.email || "Đã đăng nhập";
    googleLoginBtn.textContent = "Đăng xuất";
  } else {
    authStatusBadge.textContent = "Chưa đăng nhập";
    googleLoginBtn.textContent = "Đăng nhập với Google";
  }

  const credits = state.userInfo?.credits;
  creditTotalEl.textContent = String(credits?.total ?? 0);
  creditSubEl.textContent = String(credits?.subscription ?? 0);
  creditOneTimeEl.textContent = String(credits?.one_time ?? 0);
}

/**
 * Gọi trực tiếp `GET /auth/v1/user_info` (hoặc qua background `SYNC_USER_INFO`),
 * lưu `userInfo` vào `chrome.storage.local` và cập nhật ngay lập tức số dư Credit trên UI Popup.
 */
async function fetchAndSyncUserInfo(
  serverUrl: string,
  accessToken: string
): Promise<void> {
  const cleanToken = (accessToken || "").trim();
  const cleanServerUrl = (serverUrl || "http://127.0.0.1:8000").replace(
    /\/$/,
    ""
  );

  if (!cleanToken) {
    await chrome.storage.local.set({ userInfo: null });
    chrome.runtime.sendMessage({ type: "GET_STATE" }, (resp) => {
      if (resp?.ok && resp.state) {
        renderState(resp.state);
      }
    });
    return;
  }

  try {
    const resp = await fetch(`${cleanServerUrl}/auth/v1/user_info`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${cleanToken}`,
        Accept: "application/json",
      },
    });

    if (resp.ok) {
      const data = await resp.json();
      const normalizedUserInfo = {
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

      await chrome.storage.local.set({ userInfo: normalizedUserInfo });
      chrome.runtime.sendMessage(
        { type: "SET_CONFIG", patch: { userInfo: normalizedUserInfo } },
        (bgResp) => {
          if (bgResp?.ok && bgResp.state) {
            renderState(bgResp.state);
          }
        }
      );
      return;
    }
  } catch {
    // Fallback sang background worker nếu fetch trực tiếp từ popup gặp lỗi mạng
  }

  chrome.runtime.sendMessage({ type: "SYNC_USER_INFO" }, (bgResp) => {
    if (bgResp?.state) {
      renderState(bgResp.state);
    }
  });
}

/**
 * Lưu cấu hình Server / Token và đồng bộ ngay lập tức `user_info` + `credits` từ Backend.
 */
async function saveSettings(): Promise<void> {
  const serverUrl = inputServerUrl.value.trim() || "http://127.0.0.1:8000";
  const accessToken = inputAccessToken.value.trim();
  const refreshToken = inputRefreshToken.value.trim();
  const customContext = inputCustomContext.value
    .trim()
    .slice(0, MAX_CUSTOM_CONTEXT_LENGTH);

  await new Promise<void>((resolve) => {
    chrome.runtime.sendMessage(
      {
        type: "SET_CONFIG",
        patch: {
          serverUrl,
          accessToken,
          refreshToken,
          customContext,
        },
      },
      (resp) => {
        if (resp?.ok && resp.state) {
          renderState(resp.state);
        }
        resolve();
      }
    );
  });

  if (accessToken) {
    await fetchAndSyncUserInfo(serverUrl, accessToken);
  }
}

/**
 * Khi mở Popup (DOMContentLoaded / onMounted):
 * 1. Đọc state hiện có trong `chrome.storage.local` để hiển thị tức thì.
 * 2. Nếu có `accessToken`, tự động gọi `GET /auth/v1/user_info` để cập nhật số dư credit thực tế sau khi đọc truyện.
 */
function initPopupOnMount(): void {
  checkActiveTabSupport();

  chrome.runtime.sendMessage({ type: "GET_STATE" }, (resp) => {
    if (resp?.ok && resp.state) {
      renderState(resp.state);
      if (resp.state.accessToken) {
        void fetchAndSyncUserInfo(
          resp.state.serverUrl || "http://127.0.0.1:8000",
          resp.state.accessToken
        );
      }
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initPopupOnMount);
} else {
  initPopupOnMount();
}

inputCustomContext.addEventListener("input", () => {
  saveCustomContext(inputCustomContext.value);
});

document.querySelectorAll<HTMLButtonElement>(".preset-chip").forEach((chipBtn) => {
  chipBtn.addEventListener("click", () => {
    const presetId = chipBtn.getAttribute(
      "data-preset-id"
    ) as ContextPresetChip["id"];
    const nextText = applyContextPreset(inputCustomContext.value, presetId);
    saveCustomContext(nextText);
  });
});

requestSiteBtn.addEventListener("click", () => {
  requestSiteMsg.textContent = "Đã ghi nhận yêu cầu hỗ trợ trang web này!";
});

toggleEnabled.addEventListener("change", () => {
  chrome.runtime.sendMessage(
    { type: "SET_CONFIG", patch: { enabled: toggleEnabled.checked } },
    (resp) => {
      if (resp?.ok && resp.state) renderState(resp.state);
    }
  );
});

toggleDebugSelector.addEventListener("change", () => {
  chrome.runtime.sendMessage(
    {
      type: "SET_CONFIG",
      patch: { debugSelectorMode: toggleDebugSelector.checked },
    },
    (resp) => {
      if (resp?.ok && resp.state) renderState(resp.state);
    }
  );
});

googleLoginBtn.addEventListener("click", () => {
  if (inputAccessToken.value.trim()) {
    chrome.runtime.sendMessage({ type: "LOGOUT" }, (resp) => {
      if (resp?.ok && resp.state) renderState(resp.state);
    });
    return;
  }
  chrome.runtime.sendMessage({ type: "LOGIN_GOOGLE" }, (resp) => {
    if (resp?.ok && resp.state) {
      renderState(resp.state);
    }
  });
});

topupCreditBtn.addEventListener("click", () => {
  const baseUrl = (inputServerUrl.value || "http://127.0.0.1:8000").replace(
    /\/$/,
    ""
  );
  chrome.tabs.create({ url: `${baseUrl}/billing/v1/packages` });
});

saveConfigBtn.addEventListener("click", () => {
  void saveSettings();
});
