import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  SafeAreaView,
  FlatList,
  Alert,
  ActivityIndicator,
  TextInput,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as WebBrowser from 'expo-web-browser';
import * as Linking from 'expo-linking';
import { useSelector, useDispatch } from 'react-redux';
import { RootState } from '../store';
import { loginSuccess, logout, updateUserInfo } from '../store/authSlice';
import { setServerUrl } from '../store/settingsSlice';
import { loginWithFirebaseToken, fetchUserInfo } from '../api/comicApi';
import { getHistoryItems, clearHistory, HistoryItem } from '../database/db';
import { ServerConfigModal } from '../components/ServerConfigModal';
import { sendLocalNotification } from '../utils/notifications';

// Đảm bảo WebBrowser xử lý redirect sạch sẽ trong Expo Go
WebBrowser.maybeCompleteAuthSession();

export const ProfileScreen: React.FC = () => {
  const dispatch = useDispatch();
  const { user, accessToken } = useSelector((state: RootState) => state.auth);
  const { serverUrl } = useSelector((state: RootState) => state.settings);

  const [historyList, setHistoryList] = useState<HistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loggingIn, setLoggingIn] = useState(false);
  const [refreshingUser, setRefreshingUser] = useState(false);
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [customEmail, setCustomEmail] = useState('');

  // Tải lịch sử SQLite
  const loadHistory = async () => {
    try {
      setLoadingHistory(true);
      const items = await getHistoryItems();
      setHistoryList(items);
    } catch {
      // Ignored
    } finally {
      setLoadingHistory(false);
    }
  };

  useEffect(() => {
    loadHistory();
    // Đồng bộ thông tin user thật từ server nếu đã có accessToken
    if (accessToken) {
      handleRefreshUserInfo();
    }
  }, []);

  // Đồng bộ số dư credit thật từ Database backend
  const handleRefreshUserInfo = async () => {
    if (!accessToken) return;
    try {
      setRefreshingUser(true);
      const info = await fetchUserInfo(serverUrl, accessToken);
      dispatch(updateUserInfo(info));
    } catch {
      // Server chưa bật hoặc token hết hạn
    } finally {
      setRefreshingUser(false);
    }
  };

  // 1. ĐĂNG NHẬP GOOGLE QUA WEBBROWSER OAUTH (Expo Go Deep Link)
  const handleGoogleLogin = async () => {
    try {
      setLoggingIn(true);
      const redirectUrl = Linking.createURL('callback');
      const cleanServer = (serverUrl || 'http://172.20.10.3:8000').replace(/\/$/, '');
      const authUrl = `${cleanServer}/login/?redirect_uri=${encodeURIComponent(redirectUrl)}`;

      console.log('[AUTH] Mở WebBrowser đăng nhập Google:', authUrl);
      console.log('[AUTH] Đang chờ callback chuyển về:', redirectUrl);

      const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);

      if (result.type === 'success' && result.url) {
        const url = result.url;
        const hashIdx = url.indexOf('#');
        const queryIdx = url.indexOf('?');
        const paramStr =
          hashIdx !== -1
            ? url.substring(hashIdx + 1)
            : queryIdx !== -1
            ? url.substring(queryIdx + 1)
            : '';

        const params = new URLSearchParams(paramStr);
        const token = params.get('access_token');
        const refreshToken = params.get('refresh_token') || '';

        if (token) {
          const userInfo = await fetchUserInfo(cleanServer, token);
          dispatch(
            loginSuccess({
              user: userInfo,
              accessToken: token,
              refreshToken,
            })
          );
          await sendLocalNotification(
            'Đăng nhập Google thành công',
            `Chào mừng ${userInfo.name}! Tài khoản của bạn có ${userInfo.credits.total} Credit.`
          );
          Alert.alert(
            'Đăng nhập Google thành công',
            `Chào mừng ${userInfo.name}!\nTài khoản đồng bộ với ${userInfo.credits.total} Credit.`
          );
        } else {
          Alert.alert('Lỗi đăng nhập', 'Không tìm thấy thông tin xác thực từ server.');
        }
      }
    } catch (err: any) {
      Alert.alert(
        'Lỗi đăng nhập Google',
        err.message || 'Không thể mở cửa sổ đăng nhập Google. Hãy kiểm tra kết nối tới Server PC.'
      );
    } finally {
      setLoggingIn(false);
    }
  };

  // 2. ĐĂNG NHẬP NHANH DEV / SINH VIÊN (Cấp 20 Credit thật vào Database)
  const handleDevLogin = async (emailToUse?: string) => {
    try {
      setLoggingIn(true);
      const targetEmail = (emailToUse || 'student@mma301.fpt.edu.vn').trim().toLowerCase();
      const devToken = `dev_token_${targetEmail}`;

      const res = await loginWithFirebaseToken(serverUrl, devToken);
      const userInfo = res.user_info || (res as any).user;
      const token = res.access_token || (res as any).tokens?.access_token;
      const refreshToken = res.refresh_token || (res as any).tokens?.refresh_token;

      if (userInfo && token) {
        dispatch(
          loginSuccess({
            user: userInfo,
            accessToken: token,
            refreshToken: refreshToken || '',
          })
        );
        await sendLocalNotification(
          'Đăng nhập Dev MMA301 thành công',
          `Chào mừng ${userInfo.name}! Bạn được cấp ${userInfo.credits.total} Credit để dịch truyện.`
        );
        Alert.alert(
          'Đăng nhập thành công',
          `Chào mừng ${userInfo.name}!\nTài khoản đã được tạo trên Database thật với ${userInfo.credits.total} Credit.`
        );
      }
    } catch (error: any) {
      Alert.alert(
        'Lỗi kết nối Backend',
        `${error.message}\n\nHãy đảm bảo Server PC đang chạy tại ${serverUrl}`
      );
    } finally {
      setLoggingIn(false);
    }
  };

  // 3. ĐĂNG XUẤT TÀI KHOẢN
  const handleLogout = () => {
    Alert.alert('Đăng xuất', 'Bạn có chắc chắn muốn đăng xuất tài khoản?', [
      { text: 'Hủy', style: 'cancel' },
      {
        text: 'Đăng xuất',
        style: 'destructive',
        onPress: () => {
          dispatch(logout());
          Alert.alert('Thông báo', 'Đã đăng xuất tài khoản.');
        },
      },
    ]);
  };

  // Xóa lịch sử SQLite
  const handleClearHistory = async () => {
    Alert.alert('Xác nhận', 'Bạn có chắc muốn xóa lịch sử đọc truyện lưu trong SQLite?', [
      { text: 'Hủy', style: 'cancel' },
      {
        text: 'Xóa',
        style: 'destructive',
        onPress: async () => {
          await clearHistory();
          setHistoryList([]);
        },
      },
    ]);
  };

  const renderHistoryItem = ({ item }: { item: HistoryItem }) => (
    <View style={styles.historyCard}>
      <View style={styles.historyLeft}>
        <Ionicons name="book-outline" size={20} color="#F97316" />
        <View style={styles.historyTextContainer}>
          <Text style={styles.historyTitle} numberOfLines={1}>
            {item.title || 'Truyện tranh'}
          </Text>
          <Text style={styles.historyUrl} numberOfLines={1}>
            {item.url}
          </Text>
          <Text style={styles.historyTime}>{item.created_at}</Text>
        </View>
      </View>
      <View style={styles.historyBadge}>
        <Text style={styles.historyBadgeText}>
          {item.translated_count > 0 ? `${item.translated_count} thoại` : 'Đã xem'}
        </Text>
      </View>
    </View>
  );

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        {/* User Profile Card */}
        <View style={styles.userCard}>
          <View style={styles.avatarRow}>
            <View
              style={[
                styles.avatarCircle,
                user ? { backgroundColor: '#F97316' } : { backgroundColor: '#E2E8F0' },
              ]}
            >
              <Ionicons
                name={user ? 'person' : 'person-outline'}
                size={28}
                color={user ? "#FFFFFF" : "#64748B"}
              />
            </View>
            <View style={styles.userInfo}>
              <View style={styles.nameHeaderRow}>
                <Text style={styles.userName}>
                  {user ? user.name : 'Khách vãng lai'}
                </Text>
                {accessToken && (
                  <TouchableOpacity onPress={handleRefreshUserInfo} disabled={refreshingUser}>
                    <Ionicons
                      name="refresh"
                      size={18}
                      color="#EA580C"
                      style={refreshingUser ? { opacity: 0.5 } : {}}
                    />
                  </TouchableOpacity>
                )}
              </View>
              <Text style={styles.userEmail}>
                {user ? user.email : 'Chưa đăng nhập'}
              </Text>
              <View style={styles.badgeRow}>
                <View style={styles.roleBadge}>
                  <Text style={styles.roleBadgeText}>
                    {user ? user.tier : 'Free'}
                  </Text>
                </View>
                <View style={styles.creditBadge}>
                  <Ionicons name="wallet-outline" size={13} color="#EA580C" />
                  <Text style={styles.creditBadgeText}>
                    {user ? user.credits.total : 0} Credit
                  </Text>
                </View>
              </View>
            </View>
          </View>

          {/* Logged in action buttons */}
          {user && (
            <View style={styles.userActionRow}>
              <TouchableOpacity
                style={styles.refreshBtn}
                onPress={handleRefreshUserInfo}
                disabled={refreshingUser}
              >
                <Ionicons name="sync-outline" size={15} color="#EA580C" />
                <Text style={styles.refreshBtnText}>
                  {refreshingUser ? 'Đang tải...' : 'Làm mới số dư'}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout}>
                <Ionicons name="log-out-outline" size={15} color="#F87171" />
                <Text style={styles.logoutBtnText}>Đăng xuất</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>

        {/* AUTH BUTTONS SECTION */}
        {loggingIn ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="small" color="#EA580C" />
            <Text style={styles.loadingText}>Đang tiến hành xác thực tài khoản...</Text>
          </View>
        ) : (
          <View style={styles.authBtnGroup}>
            {user && user.email.startsWith('student@') && (
              <View style={styles.demoNotice}>
                <Ionicons name="information-circle" size={16} color="#FBBF24" />
                <Text style={styles.demoNoticeText}>
                  Đang dùng tài khoản Sinh viên demo. Bạn có thể bấm nút dưới để đăng nhập tài khoản Google của chính bạn!
                </Text>
              </View>
            )}

            {/* 1. NÚT ĐĂNG NHẬP GOOGLE */}
            <TouchableOpacity
              style={styles.googleLoginBtn}
              onPress={handleGoogleLogin}
              activeOpacity={0.85}
            >
              <Ionicons name="logo-google" size={20} color="#EA4335" />
              <Text style={styles.googleLoginBtnText}>
                {user && !user.email.startsWith('student@')
                  ? 'Đổi sang tài khoản Google khác'
                  : 'Đăng nhập với Google (Đồng bộ PC)'}
              </Text>
            </TouchableOpacity>

            {/* 2. NÚT ĐĂNG NHẬP DEV MMA301 */}
            <TouchableOpacity
              style={styles.devLoginBtn}
              onPress={() => handleDevLogin('student@mma301.fpt.edu.vn')}
              activeOpacity={0.85}
            >
              <Ionicons name="shield-checkmark-outline" size={18} color="#FFFFFF" />
              <Text style={styles.devLoginBtnText}>
                Đăng nhập 1-Click (Sinh viên MMA301 • 20 Credit)
              </Text>
            </TouchableOpacity>

            {/* 3. NHẬP EMAIL ĐỒNG BỘ TÀI KHOẢN TRỰC TIẾP */}
            <View style={styles.directEmailCard}>
              <Text style={styles.directEmailTitle}>Đồng bộ với Email Google của bạn trên PC:</Text>
              <View style={styles.directEmailRow}>
                <TextInput
                  style={styles.directEmailInput}
                  placeholder="Ví dụ: yourname@gmail.com"
                  placeholderTextColor="#64748B"
                  value={customEmail}
                  onChangeText={setCustomEmail}
                  autoCapitalize="none"
                  keyboardType="email-address"
                />
                <TouchableOpacity
                  style={styles.directEmailBtn}
                  onPress={() => {
                    if (!customEmail.trim() || !customEmail.includes('@')) {
                      Alert.alert('Lỗi', 'Vui lòng nhập địa chỉ email hợp lệ.');
                      return;
                    }
                    handleDevLogin(customEmail.trim());
                  }}
                >
                  <Text style={styles.directEmailBtnText}>Đồng bộ</Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>
        )}

        {/* Server Config & IP Banner */}
        <TouchableOpacity
          style={styles.serverRow}
          onPress={() => setConfigModalVisible(true)}
        >
          <View style={styles.serverLeft}>
            <Ionicons name="server-outline" size={20} color="#F97316" />
            <View>
              <Text style={styles.serverTitle}>Máy chủ PC Backend (FastAPI)</Text>
              <Text style={styles.serverSubtitle}>{serverUrl}</Text>
            </View>
          </View>
          <Ionicons name="chevron-forward" size={18} color="#94A3B8" />
        </TouchableOpacity>

        {/* SQLite Reading History Header */}
        <View style={styles.historyHeader}>
          <View style={styles.historyHeaderLeft}>
            <Ionicons name="time-outline" size={18} color="#F8FAFC" />
            <Text style={styles.historySectionTitle}>Lịch sử đọc & dịch (SQLite)</Text>
          </View>
          {historyList.length > 0 && (
            <TouchableOpacity onPress={handleClearHistory}>
              <Text style={styles.clearBtnText}>Xóa tất cả</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* SQLite History List */}
        {historyList.length === 0 ? (
          <View style={styles.emptyContainer}>
            <Ionicons name="library-outline" size={38} color="#475569" />
            <Text style={styles.emptyText}>Chưa có lịch sử truyện nào được lưu.</Text>
            <Text style={styles.emptySubtext}>
              Khi bạn lướt web và bấm "Dịch trang", truyện sẽ tự lưu vào SQLite offline tại đây.
            </Text>
          </View>
        ) : (
          <FlatList
            data={historyList}
            keyExtractor={(item) => String(item.id)}
            renderItem={renderHistoryItem}
            contentContainerStyle={styles.historyList}
            refreshing={loadingHistory}
            onRefresh={loadHistory}
            showsVerticalScrollIndicator={false}
          />
        )}

        {/* Footer Project Tag */}
        <View style={styles.footer}>
          <Text style={styles.footerText}>
            MMA301 - Mobile Programming • Comic Translate Client
          </Text>
        </View>
      </View>

      <ServerConfigModal
        visible={configModalVisible}
        currentUrl={serverUrl}
        onClose={() => setConfigModalVisible(false)}
        onSave={(newUrl) => dispatch(setServerUrl(newUrl))}
      />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#F8FAFC',
  },
  container: {
    flex: 1,
    padding: 16,
  },
  userCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 18,
    padding: 16,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.04,
    shadowRadius: 4,
    elevation: 2,
  },
  avatarRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
  },
  avatarCircle: {
    width: 54,
    height: 54,
    borderRadius: 27,
    alignItems: 'center',
    justifyContent: 'center',
  },
  userInfo: {
    flex: 1,
  },
  nameHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  userName: {
    color: '#0F172A',
    fontSize: 16,
    fontWeight: '700',
  },
  userEmail: {
    color: '#64748B',
    fontSize: 12,
    marginTop: 2,
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 6,
  },
  roleBadge: {
    backgroundColor: '#F1F5F9',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  roleBadgeText: {
    color: '#475569',
    fontSize: 11,
    fontWeight: '700',
  },
  creditBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#FFF7ED',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#FED7AA',
  },
  creditBadgeText: {
    color: '#EA580C',
    fontSize: 11,
    fontWeight: '700',
  },
  userActionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: 10,
    marginTop: 14,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#F1F5F9',
  },
  refreshBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: '#FFF7ED',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#FED7AA',
  },
  refreshBtnText: {
    color: '#EA580C',
    fontSize: 12,
    fontWeight: '600',
  },
  logoutBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: '#FEF2F2',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#FECACA',
  },
  logoutBtnText: {
    color: '#EF4444',
    fontSize: 12,
    fontWeight: '600',
  },
  authBtnGroup: {
    gap: 8,
    marginBottom: 12,
  },
  demoNotice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#FFFBEB',
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#FDE68A',
    marginBottom: 4,
  },
  demoNoticeText: {
    color: '#92400E',
    fontSize: 12,
    flex: 1,
  },
  googleLoginBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    backgroundColor: '#FFFFFF',
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 3,
    elevation: 2,
  },
  googleLoginBtnText: {
    color: '#0F172A',
    fontSize: 13,
    fontWeight: '700',
  },
  devLoginBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#F97316',
    paddingVertical: 12,
    borderRadius: 12,
    shadowColor: '#F97316',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 3,
  },
  devLoginBtnText: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: '700',
  },
  directEmailCard: {
    backgroundColor: '#FFFFFF',
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    marginTop: 4,
  },
  directEmailTitle: {
    color: '#475569',
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 8,
  },
  directEmailRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  directEmailInput: {
    flex: 1,
    backgroundColor: '#F8FAFC',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    color: '#0F172A',
    fontSize: 13,
    borderWidth: 1,
    borderColor: '#CBD5E1',
  },
  directEmailBtn: {
    backgroundColor: '#F97316',
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: 8,
  },
  directEmailBtnText: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: '700',
  },
  loadingContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    paddingVertical: 14,
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    marginBottom: 12,
  },
  loadingText: {
    color: '#64748B',
    fontSize: 12,
  },
  serverRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#FFFFFF',
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    marginBottom: 14,
  },
  serverLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  serverTitle: {
    color: '#0F172A',
    fontSize: 13,
    fontWeight: '600',
  },
  serverSubtitle: {
    color: '#64748B',
    fontSize: 11,
    fontFamily: 'monospace',
    marginTop: 2,
  },
  historyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  historyHeaderLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  historySectionTitle: {
    color: '#0F172A',
    fontSize: 14,
    fontWeight: '700',
  },
  clearBtnText: {
    color: '#EF4444',
    fontSize: 12,
    fontWeight: '600',
  },
  historyList: {
    paddingBottom: 16,
  },
  historyCard: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    padding: 12,
    borderRadius: 10,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  historyLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    flex: 1,
  },
  historyTextContainer: {
    flex: 1,
  },
  historyTitle: {
    color: '#0F172A',
    fontSize: 13,
    fontWeight: '600',
  },
  historyUrl: {
    color: '#64748B',
    fontSize: 11,
    marginTop: 2,
  },
  historyTime: {
    color: '#94A3B8',
    fontSize: 10,
    marginTop: 2,
  },
  historyBadge: {
    backgroundColor: '#FFF7ED',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: '#FED7AA',
  },
  historyBadgeText: {
    color: '#EA580C',
    fontSize: 11,
    fontWeight: '700',
  },
  emptyContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
  },
  emptyText: {
    color: '#475569',
    fontSize: 13,
    fontWeight: '600',
    marginTop: 10,
  },
  emptySubtext: {
    color: '#94A3B8',
    fontSize: 11,
    textAlign: 'center',
    marginTop: 6,
  },
  footer: {
    alignItems: 'center',
    paddingVertical: 6,
  },
  footerText: {
    color: '#94A3B8',
    fontSize: 11,
  },
});
