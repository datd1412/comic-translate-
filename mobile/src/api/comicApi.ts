import * as FileSystem from 'expo-file-system/legacy';
import { detectDefaultServerUrl } from '../store/settingsSlice';

export interface PayOSOrder {
  order_id: string;
  amount: number;
  credits: number;
  qr_code_url: string;
  bank_name: string;
  account_number: string;
  account_name: string;
  transfer_content: string;
}

export interface TranslatedBlock {
  id: number;
  bbox: [number, number, number, number]; // [x1, y1, x2, y2]
  source_text: string;
  translation: string;
}

export interface UserCredits {
  subscription: number;
  one_time: number;
  total: number;
}

export interface UserInfo {
  email: string;
  name: string;
  tier: string;
  email_verified?: boolean;
  credits: UserCredits;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  user_info: UserInfo;
}

export interface TranslateApiResponse {
  blocks: TranslatedBlock[];
  lang_pair: string;
  reading_direction?: string;
  cached: boolean;
  charged_credits: number;
  credits: UserCredits;
}

export interface TopupPackage {
  package_code: string;
  title: string;
  amount_vnd: number;
  credits: number;
  tier: string;
}

export interface PayOSCheckoutResponse {
  order_code: number;
  amount_vnd: number;
  credits: number;
  checkout_url: string;
  status: string;
}

export interface OrderStatusResponse {
  order_code: number;
  package_code: string;
  amount_vnd: number;
  credits: number;
  status: string;
  paid_at?: string;
}

/**
 * Kiểm tra trạng thái máy chủ thật (Health check)
 */
export const checkServerStatus = async (
  serverUrl: string
): Promise<{ ok: boolean; message: string }> => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${serverUrl}/healthz`, {
      headers: { 'ngrok-skip-browser-warning': '69420' },
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (res.ok) {
      return { ok: true, message: 'Máy chủ Backend đang kết nối tốt (Online)' };
    }
    return { ok: false, message: `Máy chủ trả về HTTP ${res.status}` };
  } catch (error: any) {
    return {
      ok: false,
      message:
        error.name === 'AbortError'
          ? 'Quá thời gian chờ phản hồi (Timeout)'
          : 'Không thể kết nối tới IP máy tính. Hãy kiểm tra Wi-Fi.',
    };
  }
};

export const checkServerHealth = checkServerStatus;

/**
 * Đăng nhập thật vào Backend qua /auth/firebase
 * Hỗ trợ cả Firebase ID Token thật và Token Dev chuẩn của hệ thống:
 * 'dev_token_student@mma301.fpt.edu.vn'
 */
export const loginWithFirebaseToken = async (
  serverUrl: string,
  idToken: string
): Promise<AuthResponse> => {
  const cleanServer = (serverUrl || detectDefaultServerUrl()).replace(/\/$/, '');
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 8000);
  try {
    const res = await fetch(`${cleanServer}/auth/firebase`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'ngrok-skip-browser-warning': '69420',
      },
      body: JSON.stringify({ id_token: idToken }),
      signal: controller.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `Lỗi đăng nhập (HTTP ${res.status})`);
    }

    return await res.json();
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      throw new Error(
        `Máy chủ (${cleanServer}) không phản hồi sau 8 giây. Hãy kiểm tra cửa sổ Terminal chạy Server trên PC (nhấn Enter nếu cửa sổ PowerShell đang bị đóng băng).`
      );
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
};

/**
 * Làm mới Access Token bằng Refresh Token khi hết hạn
 */
export const refreshAccessToken = async (
  serverUrl: string,
  refreshToken: string
): Promise<{ access_token: string; refresh_token: string }> => {
  const cleanServer = (serverUrl || detectDefaultServerUrl()).replace(/\/$/, '');
  const res = await fetch(`${cleanServer}/auth/v1/refresh`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'ngrok-skip-browser-warning': '69420',
    },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!res.ok) {
    throw new Error(`Refresh token thất bại (HTTP ${res.status})`);
  }

  return await res.json();
};

/**
 * Kiểm tra trạng thái đăng nhập theo request_id (dự phòng khi Custom Tabs chặn redirect exp://)
 */
export const pollAuthSession = async (
  serverUrl: string,
  requestId: string
): Promise<AuthResponse | null> => {
  try {
    const cleanServer = (serverUrl || detectDefaultServerUrl()).replace(/\/$/, '');
    const res = await fetch(
      `${cleanServer}/auth/v1/poll_session?request_id=${encodeURIComponent(requestId)}`,
      { headers: { 'ngrok-skip-browser-warning': '69420' } }
    );
    if (!res.ok) return null;
    const data = await res.json();
    if (data && data.status === 'completed' && data.access_token) {
      return {
        access_token: data.access_token,
        refresh_token: data.refresh_token || '',
        user_info: data.user_info,
      };
    }
    return null;
  } catch {
    return null;
  }
};

/**
 * Lấy thông tin user và số dư Credit thật từ Database Backend
 */
export const fetchUserInfo = async (
  serverUrl: string,
  accessToken: string
): Promise<UserInfo> => {
  const cleanServer = (serverUrl || detectDefaultServerUrl()).replace(/\/$/, '');
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 8000);
  try {
    const res = await fetch(`${cleanServer}/auth/v1/user_info`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: 'application/json',
        'ngrok-skip-browser-warning': '69420',
      },
      signal: controller.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Lỗi lấy thông tin tài khoản (HTTP ${res.status})`);
    }

    return await res.json();
  } finally {
    clearTimeout(timeoutId);
  }
};

/**
 * Sinh danh sách URL CDN dự phòng cho Baozimh khi node phụ (như s1-mha1-nlams.bzcdn.net)
 * bị nhà mạng chặn hoặc từ chối kết nối (Connection refused 117.55.203.31:443).
 */
function buildCdnFallbackCandidates(rawUrl: string): string[] {
  const normalized = rawUrl.replace(
    /^https?:\/\/s([12])-[a-z0-9-]+\.bzcdn\.net\//i,
    'https://s$1.bzcdn.net/'
  );
  const candidates: string[] = [];
  const pushUnique = (u: string) => {
    if (u && !candidates.includes(u)) {
      candidates.push(u);
    }
  };

  pushUnique(normalized);
  if (/^https?:\/\/[^/]*bzcdn\.net\//i.test(rawUrl)) {
    pushUnique(rawUrl.replace(/^https?:\/\/[^/]*bzcdn\.net\//i, 'https://s2.bzcdn.net/'));
    pushUnique(rawUrl.replace(/^https?:\/\/[^/]*bzcdn\.net\//i, 'https://s1.bzcdn.net/'));
  }
  pushUnique(rawUrl);
  return candidates;
}

/**
 * Cơ chế gửi ảnh chuẩn 100% của Extension (giống fetchImageBlobInBackground):
 * - Ưu tiên nhận imageDataUrl trích xuất trực tiếp từ bộ nhớ đệm Chromium của WebView.
 * - Nếu cần tải lại từ CDN, tự động chuẩn hóa & xoay vòng qua các mirror sống (s1.bzcdn.net / s2.bzcdn.net).
 * - Gửi file nhị phân lên Backend FastAPI (/api/v1/page/translate).
 */
export const translatePageWithImageUrl = async (
  serverUrl: string,
  accessToken: string,
  params: {
    imageUrl: string;
    imageDataUrl?: string;
    refererOrigin?: string;
    langPair: string;
    readingDirection?: 'rtl' | 'ltr';
    pageTitle?: string;
  }
): Promise<TranslateApiResponse> => {
  let cleanImgUrl = (params.imageUrl || '').trim();
  if (cleanImgUrl.startsWith('//')) {
    cleanImgUrl = 'https:' + cleanImgUrl;
  } else if (cleanImgUrl.startsWith('/') && params.refererOrigin) {
    cleanImgUrl = params.refererOrigin.replace(/\/$/, '') + cleanImgUrl;
  }

  const inlineDataUrl =
    params.imageDataUrl && params.imageDataUrl.startsWith('data:image/')
      ? params.imageDataUrl
      : cleanImgUrl.startsWith('data:image/')
      ? cleanImgUrl
      : '';

  const lowerUrl = (inlineDataUrl || cleanImgUrl).toLowerCase();
  const fileExt = lowerUrl.includes('png')
    ? 'png'
    : lowerUrl.includes('webp')
    ? 'webp'
    : 'jpg';
  const localFilePath = `${FileSystem.cacheDirectory}ctvn_page_${Date.now()}.${fileExt}`;

  // 1. Lưu file nhị phân từ WebView cache (data URI) hoặc tải từ CDN với cơ chế xoay vòng mirror
  if (inlineDataUrl) {
    const base64Data = inlineDataUrl.split(',')[1] || '';
    await FileSystem.writeAsStringAsync(localFilePath, base64Data, {
      encoding: FileSystem.EncodingType.Base64,
    });
  } else {
    const candidates = buildCdnFallbackCandidates(cleanImgUrl);
    let downloadedOk = false;
    let lastCdnErr = '';

    for (const candidateUrl of candidates) {
      try {
        const downloadResult = await FileSystem.downloadAsync(
          candidateUrl,
          localFilePath,
          {
            headers: {
              Referer: params.refererOrigin || 'https://cn.baozimh.com/',
              Origin: params.refererOrigin || 'https://cn.baozimh.com',
              'User-Agent':
                'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36',
            },
          }
        );

        if (downloadResult.status === 200) {
          downloadedOk = true;
          break;
        }
        lastCdnErr = `HTTP ${downloadResult.status} từ ${candidateUrl}`;
      } catch (err: any) {
        lastCdnErr = err?.message || String(err);
      }
    }

    if (!downloadedOk) {
      throw new Error(
        `[CDN] Không thể tải ảnh truyện từ máy chủ ảnh gốc (${lastCdnErr})`
      );
    }
  }

  const cleanServerUrl = (serverUrl || detectDefaultServerUrl()).replace(/\/$/, '');
  const mimeType =
    fileExt === 'png'
      ? 'image/png'
      : fileExt === 'webp'
      ? 'image/webp'
      : 'image/jpeg';
  const fileName = `page.${fileExt}`;
  const idempotencyKey = `ctvn_mobile_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
  const contextJson = JSON.stringify({
    series_title: params.pageTitle || 'Comic Webtoon',
    custom_context: '',
  });

  const effectiveToken = accessToken || 'dev_token_student@mma301.fpt.edu.vn';

  // 2. Gửi file lên server bằng Native FileSystem.uploadAsync
  let uploadResult: FileSystem.FileSystemUploadResult;
  try {
    uploadResult = await FileSystem.uploadAsync(
      `${cleanServerUrl}/api/v1/page/translate`,
      localFilePath,
      {
        httpMethod: 'POST',
        uploadType: FileSystem.FileSystemUploadType.MULTIPART,
        fieldName: 'image',
        mimeType,
        parameters: {
          lang_pair: params.langPair || 'zh-vi',
          idempotency_key: idempotencyKey,
          ...(params.readingDirection ? { reading_direction: params.readingDirection } : {}),
          context_json: contextJson,
        },
        headers: { Authorization: `Bearer ${effectiveToken}` },
      }
    );
  } finally {
    FileSystem.deleteAsync(localFilePath, { idempotent: true }).catch(() => {});
  }

  if (uploadResult.status === 200) {
    return JSON.parse(uploadResult.body);
  }

  let errDetail = uploadResult.body;
  try {
    const parsed = JSON.parse(uploadResult.body);
    errDetail = parsed.detail || parsed.error || errDetail;
  } catch {}
  throw new Error(
    `${errDetail || 'Lỗi dịch trang từ server'} (HTTP ${uploadResult.status})`
  );
};

/**
 * Lấy danh sách gói nạp PayOS thật từ Backend
 */
export const fetchTopupPackages = async (
  serverUrl: string
): Promise<TopupPackage[]> => {
  const res = await fetch(`${serverUrl}/billing/v1/packages`, {
    headers: { 'ngrok-skip-browser-warning': '69420' },
  });
  if (!res.ok) {
    throw new Error('Không thể tải danh sách gói nạp từ server');
  }
  const data = await res.json();
  return data.packages || [];
};

/**
 * Tạo link thanh toán PayOS thật (/billing/v1/payos/checkout)
 */
export const createPayOSCheckout = async (
  serverUrl: string,
  accessToken: string,
  packageCode: string
): Promise<PayOSCheckoutResponse> => {
  const res = await fetch(`${serverUrl}/billing/v1/payos/checkout`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken}`,
      'ngrok-skip-browser-warning': '69420',
    },
    body: JSON.stringify({ package_code: packageCode }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Không thể tạo đơn hàng PayOS');
  }

  return await res.json();
};

/**
 * Kiểm tra trạng thái đơn hàng PayOS theo order_code
 */
export const getOrderStatus = async (
  serverUrl: string,
  accessToken: string,
  orderCode: number
): Promise<OrderStatusResponse> => {
  const res = await fetch(`${serverUrl}/billing/v1/payos/orders/${orderCode}`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'ngrok-skip-browser-warning': '69420',
    },
  });

  if (!res.ok) {
    throw new Error('Lỗi kiểm tra trạng thái đơn hàng');
  }

  return await res.json();
};
