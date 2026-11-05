import React, { useState } from 'react';
import {
  Modal,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { checkServerHealth } from '../api/comicApi';

interface ServerConfigModalProps {
  visible: boolean;
  currentUrl: string;
  onClose: () => void;
  onSave: (newUrl: string) => void;
}

export const ServerConfigModal: React.FC<ServerConfigModalProps> = ({
  visible,
  currentUrl,
  onClose,
  onSave,
}) => {
  const [url, setUrl] = useState(currentUrl);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);

  const handleTestConnection = async () => {
    try {
      setTesting(true);
      setTestResult(null);
      const res = await checkServerHealth(url.trim());
      setTestResult(res);
    } catch (err: any) {
      setTestResult({ ok: false, message: err.message || 'Lỗi không xác định' });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = () => {
    if (!url.trim()) {
      Alert.alert('Lỗi', 'Vui lòng nhập địa chỉ server');
      return;
    }
    onSave(url.trim());
    onClose();
  };

  return (
    <Modal visible={visible} animationType="slide" transparent>
      <View style={styles.overlay}>
        <View style={styles.card}>
          {/* Header */}
          <View style={styles.header}>
            <View style={styles.headerTitleRow}>
              <Ionicons name="server-outline" size={24} color="#F97316" />
              <Text style={styles.headerTitle}>Cấu hình Server PC (Local)</Text>
            </View>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
              <Ionicons name="close" size={22} color="#6B7280" />
            </TouchableOpacity>
          </View>

          <Text style={styles.subtitle}>
            Địa chỉ FastAPI server đang chạy trên máy tính:
          </Text>

          {/* URL Input */}
          <View style={styles.inputContainer}>
            <TextInput
              style={styles.input}
              value={url}
              onChangeText={setUrl}
              placeholder="http://172.20.10.3:8000"
              placeholderTextColor="#64748B"
              autoCapitalize="none"
              autoCorrect={false}
            />
          </View>

          {/* Smart Typo Detection (127.20 -> 172.20) */}
          {url.includes('127.20.') && (
            <TouchableOpacity
              style={styles.typoWarningBox}
              onPress={() => setUrl(url.replace('127.20.', '172.20.'))}
            >
              <Ionicons name="bulb-outline" size={16} color="#EA580C" />
              <Text style={styles.typoWarningText}>
                Phát hiện gõ nhầm <Text style={{ fontWeight: '700' }}>127</Text> thay vì{' '}
                <Text style={{ fontWeight: '700' }}>172</Text>! Bấm vào đây để sửa thành{' '}
                <Text style={{ fontWeight: '700' }}>{url.replace('127.20.', '172.20.')}</Text>
              </Text>
            </TouchableOpacity>
          )}

          {/* Quick presets */}
          <Text style={styles.presetLabel}>Gợi ý nhanh:</Text>
          <View style={styles.presetRow}>
            <TouchableOpacity
              style={styles.presetBtn}
              onPress={() => setUrl('http://172.20.10.3:8000')}
            >
              <Text style={styles.presetText}>Wi-Fi hiện tại (172.20.10.3)</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.presetBtn}
              onPress={() => setUrl('http://10.0.2.2:8000')}
            >
              <Text style={styles.presetText}>Máy ảo Android (10.0.2.2)</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.presetBtn}
              onPress={() => setUrl('http://127.0.0.1:8000')}
            >
              <Text style={styles.presetText}>Localhost (127.0.0.1)</Text>
            </TouchableOpacity>
          </View>

          {/* Test Status Banner */}
          {testResult && (
            <View
              style={[
                styles.statusBox,
                testResult.ok ? styles.statusBoxSuccess : styles.statusBoxError,
              ]}
            >
              <Ionicons
                name={testResult.ok ? 'checkmark-circle' : 'alert-circle'}
                size={18}
                color={testResult.ok ? '#10B981' : '#EF4444'}
              />
              <Text
                style={[
                  styles.statusText,
                  testResult.ok ? styles.statusTextSuccess : styles.statusTextError,
                ]}
              >
                {testResult.message}
              </Text>
            </View>
          )}

          {/* Test Connection Button */}
          <TouchableOpacity
            style={styles.testBtn}
            onPress={handleTestConnection}
            disabled={testing}
          >
            {testing ? (
              <ActivityIndicator color="#EA580C" />
            ) : (
              <>
                <Ionicons name="wifi-outline" size={18} color="#EA580C" />
                <Text style={styles.testBtnText}>Kiểm tra kết nối Server</Text>
              </>
            )}
          </TouchableOpacity>

          {/* Save Button */}
          <TouchableOpacity style={styles.saveBtn} onPress={handleSave}>
            <Text style={styles.saveBtnText}>Lưu cấu hình</Text>
          </TouchableOpacity>
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
    padding: 20,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.12,
    shadowRadius: 12,
    elevation: 8,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  headerTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#0F172A',
  },
  closeBtn: {
    padding: 4,
  },
  subtitle: {
    fontSize: 13,
    color: '#64748B',
    marginBottom: 12,
    lineHeight: 18,
  },
  inputContainer: {
    backgroundColor: '#F8FAFC',
    borderWidth: 1,
    borderColor: '#CBD5E1',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 14,
  },
  input: {
    fontSize: 14,
    color: '#0F172A',
    fontFamily: 'monospace',
  },
  typoWarningBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#FFF7ED',
    borderWidth: 1,
    borderColor: '#FFEDD5',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    marginTop: -6,
    marginBottom: 12,
  },
  typoWarningText: {
    fontSize: 12,
    color: '#C2410C',
    flex: 1,
    lineHeight: 16,
  },
  presetLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#475569',
    marginBottom: 6,
  },
  presetRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 14,
  },
  presetBtn: {
    backgroundColor: '#FFF7ED',
    borderWidth: 1,
    borderColor: '#FED7AA',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
  },
  presetText: {
    color: '#EA580C',
    fontSize: 12,
    fontWeight: '600',
  },
  statusBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: 10,
    borderRadius: 10,
    marginBottom: 12,
  },
  statusBoxSuccess: {
    backgroundColor: '#ECFDF5',
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  statusBoxError: {
    backgroundColor: '#FEF2F2',
    borderWidth: 1,
    borderColor: '#FECACA',
  },
  statusText: {
    fontSize: 13,
    flex: 1,
  },
  statusTextSuccess: {
    color: '#059669',
  },
  statusTextError: {
    color: '#DC2626',
  },
  testBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: '#FFF7ED',
    borderWidth: 1,
    borderColor: '#FED7AA',
    paddingVertical: 12,
    borderRadius: 12,
    marginBottom: 10,
  },
  testBtnText: {
    color: '#EA580C',
    fontSize: 14,
    fontWeight: '700',
  },
  saveBtn: {
    backgroundColor: '#F97316',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 13,
    borderRadius: 12,
    shadowColor: '#F97316',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 3,
  },
  saveBtnText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '700',
  },
});
