import * as FileSystem from 'expo-file-system/legacy';
import { File } from 'expo-file-system';
import { fetch as expoFetch } from 'expo/fetch';

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
  bbox: [number, number, number, number]; // [ymin, xmin, ymax, xmax]
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
  const res = await fetch(`${serverUrl}/auth/firebase`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id_token: idToken }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || `Lỗi đăng nhập (HTTP ${res.status})`);
  }

  return await res.json();
};

/**
 * Lấy thông tin user và số dư Credit thật từ Database Backend
 */
export const fetchUserInfo = async (
  serverUrl: string,
  accessToken: string
): Promise<UserInfo> => {
  const res = await fetch(`${serverUrl}/auth/v1/user_info`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: 'application/json',
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi lấy thông tin tài khoản (HTTP ${res.status})`);
  }

  return await res.json();
};

/**
 * Cơ chế gửi ảnh chuẩn 100% của Extension (giống fetchImageBlobInBackground):
 * - Nhận imageUrl và refererOrigin từ WebView.
 * - Tải trực tiếp file nhị phân nguyên bản (Blob/File) về cache.
 * - Đóng vào FormData chuẩn nhị phân (KHÔNG dùng chuỗi Base64).
 * - Gửi lên Backend FastAPI (/api/v1/page/translate).
 */
export const translatePageWithImageUrl = async (
  serverUrl: string,
  accessToken: string,
  params: {
    imageUrl: string;
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

  const fileExt = cleanImgUrl.toLowerCase().includes('.png') ? 'png' : 'jpg';
  const localFilePath = `${FileSystem.cacheDirectory}ctvn_page_${Date.now()}.${fileExt}`;

  // 1. Tải file nhị phân từ CDN (hỗ trợ cả Data URI và CDN có header Referer)
  if (cleanImgUrl.startsWith('data:')) {
    const base64Data = cleanImgUrl.split(',')[1] || '';
    await FileSystem.writeAsStringAsync(localFilePath, base64Data, {
      encoding: FileSystem.EncodingType.Base64,
    });
  } else {
    const downloadResult = await FileSystem.downloadAsync(
      cleanImgUrl,
      localFilePath,
      {
        headers: {
          Referer: params.refererOrigin || 'https://www.baozimh.org/',
          Origin: params.refererOrigin || 'https://www.baozimh.org',
        },
      }
    );

    if (downloadResult.status !== 200) {
      throw new Error(`Không thể tải ảnh truyện từ CDN (HTTP ${downloadResult.status})`);
    }
  }

  const cleanServerUrl = (serverUrl || 'http://172.20.10.4:8000').replace(/\/$/, '');
  const fileName = `page.${fileExt}`;
  const idempotencyKey = `ctvn_mobile_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
  const contextJson = JSON.stringify({
    series_title: params.pageTitle || 'Comic Webtoon',
    custom_context: '',
  });

  const effectiveToken = accessToken || 'dev_token_student@mma301.fpt.edu.vn';

  // SDK 58 accepts File/Blob multipart parts rather than URI descriptors.
  try {
    const formData = new FormData();
    formData.append('image', new File(localFilePath), fileName);
    formData.append('lang_pair', params.langPair || 'zh-vi');
    formData.append('idempotency_key', idempotencyKey);
    if (params.readingDirection) {
      formData.append('reading_direction', params.readingDirection);
    }
    formData.append('context_json', contextJson);

    const res = await expoFetch(`${cleanServerUrl}/api/v1/page/translate`, {
      method: 'POST',
      body: formData,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${effectiveToken}`,
      },
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `HTTP ${res.status}`);
    }
    return await res.json();
  } finally {
    await FileSystem.deleteAsync(localFilePath, { idempotent: true }).catch(() => {});
  }
};

/**
 * Lấy danh sách gói nạp PayOS thật từ Backend
 */
export const fetchTopupPackages = async (
  serverUrl: string
): Promise<TopupPackage[]> => {
  const res = await fetch(`${serverUrl}/billing/v1/packages`);
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
    },
  });

  if (!res.ok) {
    throw new Error('Lỗi kiểm tra trạng thái đơn hàng');
  }

  return await res.json();
};
