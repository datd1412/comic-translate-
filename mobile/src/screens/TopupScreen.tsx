import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  SafeAreaView,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSelector, useDispatch } from 'react-redux';
import { RootState } from '../store';
import { updateUserCredits } from '../store/authSlice';
import {
  fetchTopupPackages,
  createPayOSCheckout,
  fetchUserInfo,
  TopupPackage,
} from '../api/comicApi';
import * as WebBrowser from 'expo-web-browser';
import { sendLocalNotification } from '../utils/notifications';

const FALLBACK_PACKAGES: TopupPackage[] = [
  {
    package_code: 'pack_basic_50k',
    title: 'Gói Cơ Bản (50k)',
    amount_vnd: 50000,
    credits: 200,
    tier: 'Basic',
  },
  {
    package_code: 'pack_pro_100k',
    title: 'Gói Phổ Biến (100k)',
    amount_vnd: 100000,
    credits: 450,
    tier: 'Pro',
  },
  {
    package_code: 'pack_ultra_200k',
    title: 'Gói Siêu Cấp (200k)',
    amount_vnd: 200000,
    credits: 1000,
    tier: 'Ultra',
  },
];

export const TopupScreen: React.FC = () => {
  const dispatch = useDispatch();
  const { user, accessToken } = useSelector((state: RootState) => state.auth);
  const { serverUrl } = useSelector((state: RootState) => state.settings);

  const [packages, setPackages] = useState<TopupPackage[]>(FALLBACK_PACKAGES);
  const [loadingPackages, setLoadingPackages] = useState(false);
  const [buyingCode, setBuyingCode] = useState<string | null>(null);

  // Tải danh sách gói thật từ backend
  const loadPackages = async () => {
    try {
      setLoadingPackages(true);
      const list = await fetchTopupPackages(serverUrl);
      if (list && list.length > 0) {
        setPackages(list);
      }
    } catch {
      // Dùng fallback
    } finally {
      setLoadingPackages(false);
    }
  };

  useEffect(() => {
    loadPackages();
  }, [serverUrl]);

  // Tạo đơn hàng PayOS thật
  const handleBuyPackage = async (pkg: TopupPackage) => {
    if (!accessToken) {
      Alert.alert(
        'Yêu cầu đăng nhập',
        'Vui lòng sang tab Tài khoản để đăng nhập trước khi nạp credit.'
      );
      return;
    }

    try {
      setBuyingCode(pkg.package_code);
      const res = await createPayOSCheckout(serverUrl, accessToken, pkg.package_code);

      if (res.checkout_url) {
        // Mở cổng thanh toán VietQR / PayOS thật trên trình duyệt điện thoại
        await WebBrowser.openBrowserAsync(res.checkout_url);

        // Sau khi quay lại, tự động refresh credit từ Database
        setTimeout(async () => {
          try {
            const updated = await fetchUserInfo(serverUrl, accessToken);
            dispatch(updateUserCredits(updated.credits));
            await sendLocalNotification(
              '💳 Trạng thái nạp tiền',
              `Đã đồng bộ số dư mới: ${updated.credits.total} credit.`
            );
          } catch {}
        }, 3000);
      } else {
        Alert.alert('Thông báo', `Đơn hàng #${res.order_code} đã được tạo.`);
      }
    } catch (error: any) {
      Alert.alert(
        'Lỗi tạo thanh toán',
        `${error.message}\n\nHãy đảm bảo Server PC đang chạy tại ${serverUrl}`
      );
    } finally {
      setBuyingCode(null);
    }
  };

  const renderHeader = () => (
    <View style={styles.headerBox}>
      {/* Balance Card */}
      <View style={styles.balanceCard}>
        <View style={styles.balanceHeader}>
          <Text style={styles.balanceTitle}>Số dư khả dụng (Database thật)</Text>
          <View style={styles.planBadge}>
            <Text style={styles.planBadgeText}>{user ? user.tier : 'Free'}</Text>
          </View>
        </View>

        <View style={styles.balanceValueRow}>
          <Ionicons name="wallet-outline" size={26} color="#EA580C" />
          <Text style={styles.balanceNumber}>
            {user ? user.credits.total : 0}
          </Text>
          <Text style={styles.balanceUnit}>Credit</Text>
        </View>

        <View style={styles.creditDetailRow}>
          <Text style={styles.creditDetailText}>
            • Gói tháng: {user?.credits?.subscription ?? 0}
          </Text>
          <Text style={styles.creditDetailText}>
            • Nạp thêm: {user?.credits?.one_time ?? 0}
          </Text>
        </View>

        <Text style={styles.balanceDesc}>
          1 trang truyện tranh = 1 credit (Nhận diện chữ & dịch tiếng Việt)
        </Text>
      </View>

      <Text style={styles.sectionTitle}>Bảng giá nạp PayOS (Cổng VietQR thật)</Text>
    </View>
  );

  const renderPackageItem = ({ item }: { item: TopupPackage }) => {
    const isPro = item.tier.toLowerCase().includes('pro');
    return (
      <View style={[styles.packageCard, isPro && styles.popularCard]}>
        {isPro && (
          <View style={styles.badgeWrapper}>
            <Text style={styles.badgeText}>PHỔ BIẾN</Text>
          </View>
        )}

        <View style={styles.pkgTopRow}>
          <Text style={styles.pkgName}>{item.title}</Text>
          <Text style={styles.pkgPrice}>
            {item.amount_vnd.toLocaleString('vi-VN')} đ
          </Text>
        </View>

        <View style={styles.creditsRow}>
          <Ionicons name="wallet-outline" size={16} color="#EA580C" />
          <Text style={styles.creditsNumber}>+{item.credits} Credit</Text>
        </View>

        <TouchableOpacity
          style={[styles.buyBtn, isPro && styles.buyBtnPopular]}
          onPress={() => handleBuyPackage(item)}
          disabled={buyingCode === item.package_code}
        >
          {buyingCode === item.package_code ? (
            <ActivityIndicator color="#FFFFFF" size="small" />
          ) : (
            <>
              <Ionicons name="qr-code-outline" size={18} color={isPro ? "#FFFFFF" : "#EA580C"} />
              <Text style={[styles.buyBtnText, isPro && styles.buyBtnTextPopular]}>Nạp qua PayOS VietQR</Text>
            </>
          )}
        </TouchableOpacity>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <FlatList
        data={packages}
        keyExtractor={(item) => item.package_code}
        renderItem={renderPackageItem}
        ListHeaderComponent={renderHeader}
        contentContainerStyle={styles.listContainer}
        showsVerticalScrollIndicator={false}
        refreshing={loadingPackages}
        onRefresh={loadPackages}
      />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#F8FAFC',
  },
  listContainer: {
    padding: 16,
    paddingBottom: 32,
  },
  headerBox: {
    marginBottom: 16,
  },
  balanceCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 20,
    borderWidth: 1,
    borderColor: '#FED7AA',
    marginBottom: 20,
    shadowColor: '#F97316',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.12,
    shadowRadius: 10,
    elevation: 4,
  },
  balanceHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  balanceTitle: {
    color: '#64748B',
    fontSize: 14,
    fontWeight: '600',
  },
  planBadge: {
    backgroundColor: '#FFF7ED',
    borderWidth: 1,
    borderColor: '#FED7AA',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  planBadgeText: {
    color: '#EA580C',
    fontSize: 12,
    fontWeight: '700',
  },
  balanceValueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginVertical: 4,
  },
  balanceNumber: {
    color: '#0F172A',
    fontSize: 36,
    fontWeight: '800',
  },
  balanceUnit: {
    color: '#EA580C',
    fontSize: 18,
    fontWeight: '700',
    marginTop: 8,
  },
  creditDetailRow: {
    flexDirection: 'row',
    gap: 16,
    marginVertical: 6,
  },
  creditDetailText: {
    color: '#64748B',
    fontSize: 12,
  },
  balanceDesc: {
    color: '#94A3B8',
    fontSize: 12,
    marginTop: 6,
  },
  sectionTitle: {
    color: '#0F172A',
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 10,
  },
  packageCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 18,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    position: 'relative',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.04,
    shadowRadius: 3,
    elevation: 2,
  },
  popularCard: {
    borderColor: '#F97316',
    borderWidth: 2,
    shadowColor: '#F97316',
    shadowOpacity: 0.15,
    shadowRadius: 8,
  },
  badgeWrapper: {
    position: 'absolute',
    top: -10,
    right: 16,
    backgroundColor: '#F97316',
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 10,
  },
  badgeText: {
    color: '#FFFFFF',
    fontSize: 11,
    fontWeight: '800',
  },
  pkgTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  pkgName: {
    color: '#0F172A',
    fontSize: 15,
    fontWeight: '700',
    flex: 1,
  },
  pkgPrice: {
    color: '#EA580C',
    fontSize: 18,
    fontWeight: '800',
  },
  creditsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 14,
  },
  creditsNumber: {
    color: '#16A34A',
    fontSize: 15,
    fontWeight: '700',
  },
  buyBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#FFF7ED',
    borderWidth: 1,
    borderColor: '#FED7AA',
    paddingVertical: 12,
    borderRadius: 10,
  },
  buyBtnPopular: {
    backgroundColor: '#F97316',
    borderColor: '#F97316',
  },
  buyBtnText: {
    color: '#EA580C',
    fontSize: 14,
    fontWeight: '700',
  },
  buyBtnTextPopular: {
    color: '#FFFFFF',
  },
});
