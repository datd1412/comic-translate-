import React, { useState } from 'react';
import {
  Modal,
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Image,
  ActivityIndicator,
  Alert,
  ScrollView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { PayOSOrder } from '../api/comicApi';

interface VietQRModalProps {
  visible: boolean;
  order: PayOSOrder | null;
  onClose: () => void;
  onConfirmSuccess: (orderId: string) => Promise<void>;
}

export const VietQRModal: React.FC<VietQRModalProps> = ({
  visible,
  order,
  onClose,
  onConfirmSuccess,
}) => {
  const [confirming, setConfirming] = useState(false);

  if (!order) return null;

  const handleSimulatePayment = async () => {
    try {
      setConfirming(true);
      await onConfirmSuccess(order.order_id);
    } catch (error: any) {
      Alert.alert('Lỗi xác nhận', error.message || 'Không thể xác nhận đơn hàng');
    } finally {
      setConfirming(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent>
      <View style={styles.overlay}>
        <View style={styles.card}>
          {/* Header */}
          <View style={styles.header}>
            <View style={styles.headerTitleRow}>
              <Ionicons name="qr-code-outline" size={24} color="#F97316" />
              <Text style={styles.headerTitle}>Thanh toán VietQR / PayOS</Text>
            </View>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
              <Ionicons name="close" size={22} color="#6B7280" />
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
            {/* Amount Badge */}
            <View style={styles.amountBadge}>
              <Text style={styles.amountLabel}>Số tiền cần nạp:</Text>
              <Text style={styles.amountValue}>
                {order.amount.toLocaleString('vi-VN')} đ
              </Text>
              <Text style={styles.creditsReward}>
                🎁 Nhận ngay: +{order.credits} Credit
              </Text>
            </View>

            {/* QR Code */}
            <View style={styles.qrContainer}>
              <Image
                source={{ uri: order.qr_code_url }}
                style={styles.qrImage}
                resizeMode="contain"
              />
              <Text style={styles.qrNote}>
                Quét mã bằng ứng dụng Ngân hàng (MBBank, Vietcombank, Momo...)
              </Text>
            </View>

            {/* Bank Information Details */}
            <View style={styles.infoBox}>
              <View style={styles.infoRow}>
                <Text style={styles.infoKey}>Ngân hàng:</Text>
                <Text style={styles.infoVal}>{order.bank_name}</Text>
              </View>

              <View style={styles.infoRow}>
                <Text style={styles.infoKey}>Chủ tài khoản:</Text>
                <Text style={styles.infoValBold}>{order.account_name}</Text>
              </View>

              <View style={styles.infoRow}>
                <Text style={styles.infoKey}>Số tài khoản:</Text>
                <Text style={styles.infoValCode}>{order.account_number}</Text>
              </View>

              <View style={[styles.infoRow, styles.contentRow]}>
                <Text style={styles.infoKey}>Nội dung CK:</Text>
                <Text style={styles.contentValCode}>{order.transfer_content}</Text>
              </View>
            </View>

            {/* Action Buttons */}
            <TouchableOpacity
              style={styles.confirmBtn}
              onPress={handleSimulatePayment}
              disabled={confirming}
            >
              {confirming ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="checkmark-circle" size={20} color="#fff" />
                  <Text style={styles.confirmBtnText}>
                    Xác nhận đã thanh toán (Dev Mode)
                  </Text>
                </>
              )}
            </TouchableOpacity>

            <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
              <Text style={styles.cancelBtnText}>Đóng cửa sổ</Text>
            </TouchableOpacity>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(15, 23, 42, 0.65)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 16,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    width: '100%',
    maxHeight: '92%',
    padding: 20,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 8,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  headerTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  headerTitle: {
    color: '#0F172A',
    fontSize: 18,
    fontWeight: '700',
  },
  closeBtn: {
    padding: 6,
    borderRadius: 8,
    backgroundColor: '#F1F5F9',
  },
  scrollContent: {
    alignItems: 'center',
  },
  amountBadge: {
    backgroundColor: '#FFF7ED',
    width: '100%',
    borderRadius: 14,
    padding: 14,
    alignItems: 'center',
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#FED7AA',
  },
  amountLabel: {
    color: '#9A3412',
    fontSize: 13,
    fontWeight: '500',
  },
  amountValue: {
    color: '#EA580C',
    fontSize: 24,
    fontWeight: '800',
    marginTop: 4,
  },
  creditsReward: {
    color: '#16A34A',
    fontSize: 13,
    fontWeight: '600',
    marginTop: 4,
  },
  qrContainer: {
    backgroundColor: '#FFFFFF',
    borderRadius: 14,
    padding: 12,
    alignItems: 'center',
    width: 240,
    height: 240,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  qrImage: {
    width: 200,
    height: 200,
  },
  qrNote: {
    color: '#64748B',
    fontSize: 10,
    textAlign: 'center',
    marginTop: 4,
  },
  infoBox: {
    backgroundColor: '#F8FAFC',
    width: '100%',
    borderRadius: 12,
    padding: 12,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 5,
  },
  contentRow: {
    backgroundColor: '#FFF7ED',
    borderRadius: 6,
    paddingHorizontal: 8,
    marginTop: 4,
  },
  infoKey: {
    color: '#64748B',
    fontSize: 13,
  },
  infoVal: {
    color: '#334155',
    fontSize: 13,
    fontWeight: '500',
  },
  infoValBold: {
    color: '#0F172A',
    fontSize: 13,
    fontWeight: '700',
  },
  infoValCode: {
    color: '#EA580C',
    fontSize: 13,
    fontWeight: '700',
    fontFamily: 'monospace',
  },
  contentValCode: {
    color: '#EA580C',
    fontSize: 13,
    fontWeight: '700',
    fontFamily: 'monospace',
  },
  confirmBtn: {
    backgroundColor: '#F97316',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    width: '100%',
    paddingVertical: 14,
    borderRadius: 12,
    marginBottom: 10,
    shadowColor: '#F97316',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 3,
  },
  confirmBtnText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '700',
  },
  cancelBtn: {
    paddingVertical: 10,
  },
  cancelBtnText: {
    color: '#64748B',
    fontSize: 14,
  },
});

