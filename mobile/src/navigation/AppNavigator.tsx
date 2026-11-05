import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';
import { useSelector } from 'react-redux';
import { RootState } from '../store';
import { BrowserScreen } from '../screens/BrowserScreen';
import { TopupScreen } from '../screens/TopupScreen';
import { ProfileScreen } from '../screens/ProfileScreen';

export type RootTabParamList = {
  Browser: undefined;
  Topup: undefined;
  Profile: undefined;
};

const Tab = createBottomTabNavigator<RootTabParamList>();

export const AppNavigator: React.FC = () => {
  const { user } = useSelector((state: RootState) => state.auth);

  return (
    <Tab.Navigator
      initialRouteName="Browser"
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: {
          backgroundColor: '#FFFFFF',
          borderTopColor: '#E2E8F0',
          borderTopWidth: 1,
          height: 62,
          paddingBottom: 8,
          paddingTop: 6,
        },
        tabBarActiveTintColor: '#F97316',
        tabBarInactiveTintColor: '#94A3B8',
        tabBarLabelStyle: {
          fontSize: 12,
          fontWeight: '600',
        },
        tabBarIcon: ({ focused, color, size }) => {
          let iconName: keyof typeof Ionicons.glyphMap = 'book-outline';

          if (route.name === 'Browser') {
            iconName = focused ? 'globe' : 'globe-outline';
          } else if (route.name === 'Topup') {
            iconName = focused ? 'wallet' : 'wallet-outline';
          } else if (route.name === 'Profile') {
            iconName = focused ? (user ? 'person' : 'log-in') : (user ? 'person-outline' : 'log-in-outline');
          }

          return <Ionicons name={iconName} size={size} color={color} />;
        },
      })}
    >
      <Tab.Screen
        name="Browser"
        component={BrowserScreen}
        options={{
          tabBarLabel: 'Trình duyệt',
        }}
      />
      <Tab.Screen
        name="Topup"
        component={TopupScreen}
        options={{
          tabBarLabel: 'Nạp Credit',
        }}
      />
      <Tab.Screen
        name="Profile"
        component={ProfileScreen}
        options={{
          tabBarLabel: user ? 'Tài khoản' : 'Đăng nhập',
        }}
      />
    </Tab.Navigator>
  );
};

