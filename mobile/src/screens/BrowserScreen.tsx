import React, { useState, useRef, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  ScrollView,
  SafeAreaView,
} from 'react-native';
import { WebView, WebViewNavigation } from 'react-native-webview';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import { useSelector, useDispatch } from 'react-redux';
import { RootState } from '../store';
import { updateUserCredits, loginSuccess } from '../store/authSlice';
import {
  toggleShowOriginal,
  toggleReadingDirection,
  setLangPair,
} from '../store/settingsSlice';
import { saveHistoryItem, saveBookmarkItem, saveAppSetting } from '../database/db';
import {
  translatePageWithImageUrl,
  loginWithFirebaseToken,
  refreshAccessToken,
  TranslatedBlock,
} from '../api/comicApi';
import { MANGA_INJECTED_JS } from '../utils/injectedScript';
import { sendLocalNotification } from '../utils/notifications';

const WebViewComponent = WebView as any;

const QUICK_LINKS = [
  { name: 'Baozimh (Trung)', url: 'https://cn.baozimh.com', lang: 'zh-vi' },
  { name: 'HiveToons (Anh)', url: 'https://hivetoons.org', lang: 'en-vi' },
];

export const BrowserScreen: React.FC = () => {
  const dispatch = useDispatch();
  const navigation = useNavigation<any>();
  const webViewRef = useRef<any>(null);

  const { user, accessToken, refreshToken } = useSelector((state: RootState) => state.auth);
  const { serverUrl, showOriginal, langPair, readingDirection } = useSelector(
    (state: RootState) => state.settings
  );

  const [inputUrl, setInputUrl] = useState('https://cn.baozimh.com');
  const [currentUrl, setCurrentUrl] = useState('https://cn.baozimh.com');
  const [pageTitle, setPageTitle] = useState('Baozi Manhua');
  const [canGoBack, setCanGoBack] = useState(false);
  const [canGoForward, setCanGoForward] = useState(false);
  const [loading, setLoading] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [translatingPageIndex, setTranslatingPageIndex] = useState<number | null>(null);
  const [translatedBlocks, setTranslatedBlocks] = useState<TranslatedBlock[]>([]);

  // Tự động cập nhật script mới nhất vào WebView (kể cả khi Fast Refresh không reload trang)
  useEffect(() => {
    webViewRef.current?.injectJavaScript(MANGA_INJECTED_JS);
  }, [currentUrl]);

  // Điều hướng đến URL mới
  const handleGoToUrl = () => {
    let target = inputUrl.trim();
    if (!target) return;
    if (!target.startsWith('http://') && !target.startsWith('https://')) {
      target = 'https://' + target;
    }
    setCurrentUrl(target);
  };

  // Chọn link nhanh
  const handleSelectQuickLink = (link: { name: string; url: string; lang: string }) => {
    setInputUrl(link.url);
    setCurrentUrl(link.url);
    dispatch(setLangPair(link.lang));
  };

  // Xử lý message từ WebView gửi về (chuẩn mô hình content.ts -> background.ts)
  const handleWebViewMessage = async (event: any) => {
    try {
      const data = JSON.parse(event.nativeEvent.data);

      if (data.type === 'PAGE_READY') {
        if (data.title) setPageTitle(data.title);
      } else if (data.type === 'ERROR') {
        setTranslating(false);
        Alert.alert('Thông báo', data.message);
      } else if (data.type === 'TRANSLATE_PAGE_REQUEST') {
        if (data.pageIndex) {
          setTranslatingPageIndex(Number(data.pageIndex));
        }
        // NHẬN LINK ẢNH GỐC (imageUrl) HOẶC DỮ LIỆU ẢNH TRONG WEBVIEW (imageDataUrl) VÀ GỬI BACKEND THẬT!
        await handleProcessTranslateRequest(
          data.imageUrl,
          data.imageDataUrl || '',
          data.refererOrigin,
          data.pageTitle || pageTitle,
          data.pageUrl || currentUrl
        );
      }
    } catch {
      // Ignored
    }
  };

  // Tải file nhị phân từ imageUrl / imageDataUrl và gửi lên Backend FastAPI
  const handleProcessTranslateRequest = async (
    imageUrl: string,
    imageDataUrl: string,
    refererOrigin: string,
    title: string,
    url: string
  ) => {
    try {
      setTranslating(true);

      let tokenToUse = accessToken;

      // Đảm bảo luôn có JWT token thật (nếu chưa có hoặc là dev token giả, xin token mới)
      const fallbackEmail = user?.email || 'student@mma301.fpt.edu.vn';
      if (!tokenToUse || tokenToUse.startsWith('dev_token_')) {
        try {
          const authRes = await loginWithFirebaseToken(
            serverUrl,
            `dev_token_${fallbackEmail}`
          );
          if (authRes.access_token) {
            tokenToUse = authRes.access_token;
            const sessionPayload = {
              user: authRes.user_info,
              accessToken: authRes.access_token,
              refreshToken: authRes.refresh_token || '',
            };
            dispatch(loginSuccess(sessionPayload));
            await saveAppSetting('auth_session', JSON.stringify(sessionPayload));
          }
        } catch (authErr) {
          console.warn('Không thể tự động lấy token:', authErr);
        }
      }

      let result: any;
      try {
        result = await translatePageWithImageUrl(serverUrl, tokenToUse || '', {
          imageUrl: imageUrl,
          imageDataUrl: imageDataUrl,
          refererOrigin: refererOrigin,
          langPair: langPair,
          readingDirection: readingDirection,
          pageTitle: title,
        });
      } catch (callErr: any) {
        // Nếu gặp lỗi 401 Unauthorized (Token hết hạn), ưu tiên dùng refreshToken trước, sau đó mới fallback
        if (
          String(callErr.message || '').includes('401') ||
          String(callErr.message || '').toLowerCase().includes('unauthorized')
        ) {
          let refreshed = false;
          if (refreshToken && user) {
            try {
              const refRes = await refreshAccessToken(serverUrl, refreshToken);
              if (refRes.access_token) {
                tokenToUse = refRes.access_token;
                const sessionPayload = {
                  user,
                  accessToken: refRes.access_token,
                  refreshToken: refRes.refresh_token || refreshToken,
                };
                dispatch(loginSuccess(sessionPayload));
                await saveAppSetting('auth_session', JSON.stringify(sessionPayload));
                refreshed = true;
              }
            } catch {
              // Refresh token hết hạn -> fallback bên dưới
            }
          }

          if (!refreshed) {
            const freshAuth = await loginWithFirebaseToken(
              serverUrl,
              `dev_token_${fallbackEmail}`
            );
            tokenToUse = freshAuth.access_token;
            const sessionPayload = {
              user: freshAuth.user_info,
              accessToken: freshAuth.access_token,
              refreshToken: freshAuth.refresh_token || '',
            };
            dispatch(loginSuccess(sessionPayload));
            await saveAppSetting('auth_session', JSON.stringify(sessionPayload));
          }

          result = await translatePageWithImageUrl(serverUrl, tokenToUse || '', {
            imageUrl: imageUrl,
            imageDataUrl: imageDataUrl,
            refererOrigin: refererOrigin,
            langPair: langPair,
            readingDirection: readingDirection,
            pageTitle: title,
          });
        } else {
          throw callErr;
        }
      }

      if (result.blocks) {
        setTranslatedBlocks(result.blocks);

        // Cập nhật số dư credit thật từ Database backend
        if (result.credits) {
          dispatch(updateUserCredits(result.credits));
        }

        if (result.blocks.length === 0) {
          webViewRef.current?.injectJavaScript(
            'window.__clearTranslatingStatus && window.__clearTranslatingStatus(); true;'
          );
          Alert.alert(
            'Không tìm thấy câu thoại',
            'AI không phát hiện thấy bong bóng thoại nào trên bức ảnh này (trang bìa hoặc hình minh họa). Bạn không bị trừ credit!'
          );
        } else {
          if (showOriginal) {
            dispatch(toggleShowOriginal());
          }
          // Ra lệnh cho WebView vẽ đè các khối thoại tiếng Việt lên trang web
          const renderScript = `window.__renderRealTranslatedBlocks(${JSON.stringify(
            result.blocks
          )}, false); true;`;
          webViewRef.current?.injectJavaScript(renderScript);

          // Lưu vào SQLite
          await saveHistoryItem(url, title, result.blocks.length);

          // Bắn thông báo Local Push Notification
          await sendLocalNotification(
            '⚡ Dịch truyện thành công!',
            `AI đã nhận diện và dịch ${result.blocks.length} câu thoại. Số dư: ${result.credits?.total ?? 0} credit.`
          );
        }
      }
    } catch (error: any) {
      webViewRef.current?.injectJavaScript(
        'window.__clearTranslatingStatus && window.__clearTranslatingStatus(); true;'
      );
      const errMsg = String(error?.message || error || '');
      if (errMsg.startsWith('[CDN]') || errMsg.includes('bzcdn.net')) {
        Alert.alert(
          'Lỗi tải ảnh từ CDN truyện',
          `${errMsg.replace(/^\[CDN\]\s*/, '')}\n\nHãy cuộn trang để ảnh truyện hiện rõ trên màn hình rồi bấm Dịch lại.`
        );
      } else {
        Alert.alert(
          'Lỗi từ Backend',
          `${errMsg}\n\nHãy kiểm tra kết nối tới Server PC (${serverUrl})`
        );
      }
    } finally {
      setTranslating(false);
      setTranslatingPageIndex(null);
    }
  };

  // Nút bấm "Dịch trang này": WebView tìm link ảnh và gửi sang React Native
  const handleTriggerTranslate = () => {
    if (!user) {
      Alert.alert(
        'Chưa đăng nhập',
        'Vui lòng đăng nhập với Google (hoặc dùng tài khoản Sinh viên) để nhận 20 Credit và dịch truyện!',
        [
          { text: 'Để sau', style: 'cancel' },
          {
            text: 'Đăng nhập ngay',
            style: 'default',
            onPress: () => navigation.navigate('Profile'),
          },
        ]
      );
      return;
    }

    if (user && user.credits && user.credits.total < 1) {
      Alert.alert(
        'Hết Credit',
        'Tài khoản của bạn đã hết credit. Vui lòng chuyển sang Tab "Nạp Credit" để nạp thêm!'
      );
      return;
    }

    setTranslating(true);
    // Đảm bảo script mới nhất đã được nạp rồi kích hoạt đánh dấu khung viền mờ + trích xuất ảnh
    webViewRef.current?.injectJavaScript(
      `${MANGA_INJECTED_JS}; window.__triggerTranslateActivePage(); true;`
    );
  };

  // Xem ảnh gốc / Xem bản dịch (ẩn toàn bộ khung đè để thấy ảnh truyện gốc giống Extension)
  const handleToggleOriginal = () => {
    const nextState = !showOriginal;
    dispatch(toggleShowOriginal());
    const toggleScript = `if (window.__setShowOriginalMode) { window.__setShowOriginalMode(${nextState}); } else if (window.__renderRealTranslatedBlocks) { window.__renderRealTranslatedBlocks(${JSON.stringify(
      translatedBlocks
    )}, ${nextState}); } true;`;
    webViewRef.current?.injectJavaScript(toggleScript);
  };

  // Đổi chiều đọc RTL / LTR
  const handleToggleDirection = () => {
    dispatch(toggleReadingDirection());
  };

  // Lưu bookmark vào SQLite
  const handleBookmark = async () => {
    await saveBookmarkItem(currentUrl, pageTitle || 'Truyện tranh');
    Alert.alert('Thành công', 'Đã lưu trang vào Bookmark SQLite!');
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      {/* Top Banner Thông báo Đăng nhập / Trạng thái tài khoản */}
      <TouchableOpacity
        style={[styles.accountBanner, !user ? styles.accountBannerGuest : styles.accountBannerUser]}
        onPress={() => navigation.navigate('Profile')}
        activeOpacity={0.8}
      >
        {!user ? (
          <>
            <View style={styles.bannerLeft}>
              <View style={styles.googleIconCircle}>
                <Ionicons name="logo-google" size={13} color="#EA4335" />
              </View>
              <Text style={styles.bannerGuestText}>
                Chưa đăng nhập • <Text style={styles.highlightText}>Nhận 20 Credit miễn phí</Text>
              </Text>
            </View>
            <View style={styles.loginPill}>
              <Text style={styles.loginPillText}>Đăng nhập ➔</Text>
            </View>
          </>
        ) : (
          <>
            <View style={styles.bannerLeft}>
              <Ionicons name="person-circle" size={18} color="#EA580C" />
              <Text style={styles.bannerUserText} numberOfLines={1}>
                {user.name} ({user.email})
              </Text>
            </View>
            <View style={styles.creditPill}>
              <Ionicons name="wallet-outline" size={13} color="#EA580C" />
              <Text style={styles.creditPillText}>{user.credits.total} Credit</Text>
              <Ionicons name="chevron-forward" size={12} color="#94A3B8" />
            </View>
          </>
        )}
      </TouchableOpacity>

      {/* Top Address & Navigation Bar */}
      <View style={styles.navBar}>
        <View style={styles.addressBar}>
          <TouchableOpacity
            style={[styles.navBtn, !canGoBack && styles.navBtnDisabled]}
            onPress={() => webViewRef.current?.goBack()}
            disabled={!canGoBack}
          >
            <Ionicons name="arrow-back" size={18} color={canGoBack ? '#334155' : '#CBD5E1'} />
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.navBtn, !canGoForward && styles.navBtnDisabled]}
            onPress={() => webViewRef.current?.goForward()}
            disabled={!canGoForward}
          >
            <Ionicons name="arrow-forward" size={18} color={canGoForward ? '#334155' : '#CBD5E1'} />
          </TouchableOpacity>

          <TextInput
            style={styles.urlInput}
            value={inputUrl}
            onChangeText={setInputUrl}
            onSubmitEditing={handleGoToUrl}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            returnKeyType="go"
          />

          <TouchableOpacity style={styles.goBtn} onPress={handleGoToUrl}>
            <Ionicons name="arrow-forward-circle" size={24} color="#F97316" />
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.refreshBtn}
            onPress={() => webViewRef.current?.reload()}
          >
            <Ionicons name="reload" size={18} color="#475569" />
          </TouchableOpacity>
        </View>

        {/* Quick Links & Mode Bar */}
        <View style={styles.subBar}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.quickLinksScroll}>
            {QUICK_LINKS.map((link, idx) => (
              <TouchableOpacity
                key={idx}
                style={styles.quickPill}
                onPress={() => handleSelectQuickLink(link)}
              >
                <Text style={styles.quickPillText}>{link.name}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          {/* Reading Direction Toggle Button */}
          <TouchableOpacity style={styles.modePill} onPress={handleToggleDirection}>
            <Text style={styles.modePillText}>
              {readingDirection === 'rtl' ? 'RTL (Manga)' : 'LTR (Webtoon)'}
            </Text>
          </TouchableOpacity>

          {/* User Credits Badge */}
          <View style={styles.creditPill}>
            <Ionicons name="wallet-outline" size={13} color="#EA580C" />
            <Text style={styles.creditPillText}>
              {user ? user.credits.total : 0} Cr
            </Text>
          </View>
        </View>
      </View>

      {/* Loading Progress */}
      {loading && (
        <View style={styles.loadingBar}>
          <ActivityIndicator size="small" color="#F97316" />
          <Text style={styles.loadingText}>Đang tải trang web truyện...</Text>
        </View>
      )}

      {/* Main WebView Reader */}
      <View style={styles.webViewContainer}>
        <WebViewComponent
          ref={webViewRef}
          source={{ uri: currentUrl }}
          style={styles.webView}
          injectedJavaScript={MANGA_INJECTED_JS}
          onMessage={handleWebViewMessage}
          onNavigationStateChange={(navState: WebViewNavigation) => {
            setCanGoBack(navState.canGoBack);
            setCanGoForward(navState.canGoForward);
            setInputUrl(navState.url);
            setCurrentUrl(navState.url);
            if (navState.title) setPageTitle(navState.title);
          }}
          onLoadStart={() => setLoading(true)}
          onLoadEnd={() => {
            setLoading(false);
            webViewRef.current?.injectJavaScript(MANGA_INJECTED_JS);
          }}
          allowsBackForwardNavigationGestures
          javaScriptEnabled={true}
          domStorageEnabled={true}
          mixedContentMode="always"
        />

        {/* Floating Action Buttons (Gọn nhẹ, không che khuất khung tranh) */}
        <View style={styles.fabContainer}>
          {translatedBlocks.length > 0 && (
            <TouchableOpacity
              style={[styles.fabSecondary, showOriginal && styles.fabActive]}
              onPress={handleToggleOriginal}
              activeOpacity={0.85}
            >
              <Ionicons
                name={showOriginal ? 'eye-outline' : 'language-outline'}
                size={14}
                color={showOriginal ? '#FFFFFF' : '#EA580C'}
              />
              <Text
                style={[
                  styles.fabSecondaryText,
                  showOriginal && { color: '#FFFFFF' },
                ]}
              >
                {showOriginal ? 'Bản dịch' : 'Ảnh gốc'}
              </Text>
            </TouchableOpacity>
          )}

          <TouchableOpacity
            style={styles.fabBookmark}
            onPress={handleBookmark}
            activeOpacity={0.85}
          >
            <Ionicons name="bookmark-outline" size={15} color="#475569" />
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.fabPrimary, translating && styles.fabDisabled]}
            onPress={handleTriggerTranslate}
            disabled={translating}
            activeOpacity={0.85}
          >
            {translating ? (
              <>
                <ActivityIndicator color="#FFFFFF" size="small" style={{ transform: [{ scale: 0.75 }] }} />
                <Text style={styles.fabPrimaryText}>
                  {translatingPageIndex ? `Đang dịch #${translatingPageIndex}...` : 'Đang dịch...'}
                </Text>
              </>
            ) : (
              <>
                <Ionicons name="language-outline" size={15} color="#FFFFFF" />
                <Text style={styles.fabPrimaryText}>Dịch</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </View>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  navBar: {
    backgroundColor: '#FFFFFF',
    paddingHorizontal: 8,
    paddingTop: 8,
    paddingBottom: 6,
    borderBottomWidth: 1,
    borderBottomColor: '#E2E8F0',
  },
  addressBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  navBtn: {
    padding: 6,
    borderRadius: 8,
    backgroundColor: '#F8FAFC',
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  navBtnDisabled: {
    opacity: 0.4,
  },
  urlInput: {
    flex: 1,
    height: 38,
    backgroundColor: '#F8FAFC',
    borderRadius: 10,
    paddingHorizontal: 12,
    color: '#0F172A',
    fontSize: 13,
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  goBtn: {
    padding: 2,
  },
  refreshBtn: {
    padding: 8,
    borderRadius: 8,
    backgroundColor: '#F8FAFC',
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  subBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 8,
    gap: 6,
  },
  quickLinksScroll: {
    flexGrow: 0,
  },
  quickPill: {
    backgroundColor: '#FFF7ED',
    borderWidth: 1,
    borderColor: '#FED7AA',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 12,
    marginRight: 6,
  },
  quickPillText: {
    color: '#C2410C',
    fontSize: 11,
    fontWeight: '600',
  },
  modePill: {
    backgroundColor: '#F1F5F9',
    borderWidth: 1,
    borderColor: '#E2E8F0',
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 12,
  },
  modePillText: {
    color: '#475569',
    fontSize: 11,
    fontWeight: '700',
  },
  creditPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#FFF7ED',
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#FED7AA',
  },
  creditPillText: {
    color: '#EA580C',
    fontSize: 12,
    fontWeight: '700',
  },
  loadingBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#FFF7ED',
    paddingVertical: 5,
    borderBottomWidth: 1,
    borderBottomColor: '#FED7AA',
  },
  loadingText: {
    color: '#C2410C',
    fontSize: 12,
    fontWeight: '500',
  },
  webViewContainer: {
    flex: 1,
    position: 'relative',
    backgroundColor: '#F8FAFC',
  },
  webView: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  fabContainer: {
    position: 'absolute',
    bottom: 10,
    right: 10,
    flexDirection: 'column',
    alignItems: 'flex-end',
    gap: 6,
  },
  fabPrimary: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: 'rgba(249, 115, 22, 0.92)',
    paddingHorizontal: 11,
    paddingVertical: 7,
    borderRadius: 18,
    shadowColor: '#F97316',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 5,
  },
  fabDisabled: {
    opacity: 0.8,
  },
  fabPrimaryText: {
    color: '#FFFFFF',
    fontSize: 11.5,
    fontWeight: '700',
  },
  fabSecondary: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: 'rgba(255, 255, 255, 0.92)',
    borderWidth: 1,
    borderColor: '#FED7AA',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 3,
    elevation: 3,
  },
  fabActive: {
    backgroundColor: '#EA580C',
    borderColor: '#EA580C',
  },
  fabSecondaryText: {
    color: '#EA580C',
    fontSize: 11,
    fontWeight: '600',
  },
  fabBookmark: {
    backgroundColor: 'rgba(255, 255, 255, 0.9)',
    borderWidth: 1,
    borderColor: '#E2E8F0',
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 2,
  },
  accountBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#E2E8F0',
  },
  accountBannerGuest: {
    backgroundColor: '#FFF7ED',
    borderBottomColor: '#FED7AA',
  },
  accountBannerUser: {
    backgroundColor: '#FFFFFF',
  },
  bannerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flex: 1,
  },
  googleIconCircle: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#FED7AA',
  },
  bannerGuestText: {
    color: '#9A3412',
    fontSize: 12,
  },
  highlightText: {
    color: '#EA580C',
    fontWeight: '700',
  },
  bannerUserText: {
    color: '#0F172A',
    fontSize: 12,
    fontWeight: '600',
    flex: 1,
  },
  loginPill: {
    backgroundColor: '#F97316',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
  },
  loginPillText: {
    color: '#FFFFFF',
    fontSize: 11,
    fontWeight: '700',
  },
});
