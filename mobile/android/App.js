import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, BackHandler, Linking, Platform, SafeAreaView, StatusBar, StyleSheet, Text, View } from 'react-native';
import { WebView } from 'react-native-webview';
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';

const PORTAL = 'https://dismepeone.com.br/';
const ORIGIN = 'https://dismepeone.com.br';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false
  })
});

function isPortalUrl(url) {
  if (typeof url !== 'string') return false;
  try {
    const parsed = new URL(url, ORIGIN);
    return parsed.protocol === 'https:' && parsed.origin === ORIGIN;
  } catch (_) {
    return false;
  }
}

function safePushDestination(raw) {
  if (typeof raw !== 'string' || !raw) return PORTAL;
  try {
    const url = new URL(raw, ORIGIN);
    return isPortalUrl(url.href) ? url.href : PORTAL;
  } catch (_) {
    return PORTAL;
  }
}

async function getPushToken() {
  if (!Device.isDevice) return null;
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('avisos', {
      name: 'Avisos DISMEPE ONE',
      importance: Notifications.AndroidImportance.HIGH
    });
  }
  const existing = await Notifications.getPermissionsAsync();
  const permission = existing.granted ? existing : await Notifications.requestPermissionsAsync();
  if (!permission.granted) return null;
  const result = await Notifications.getDevicePushTokenAsync();
  if (typeof result.data !== 'string' || !result.data.trim()) return null;
  return result.data;
}

export default function App() {
  const web = useRef(null);
  const pushToken = useRef(null);
  const [pageReady, setPageReady] = useState(false);
  const [canGoBack, setCanGoBack] = useState(false);
  const [error, setError] = useState('');

  const registerInPortal = useCallback(() => {
    if (!web.current || !pushToken.current) return;
    // Endpoint /mobile/push/register ainda depende da integracao backend.
    // A sessao da propria WebView deve autenticar e vincular o token ao usuario.
    const payload = JSON.stringify({ fcmToken: pushToken.current, plataforma: 'android' });
    web.current.injectJavaScript(`(function(){
      if (window.location.origin !== ${JSON.stringify(ORIGIN)}) return true;
      fetch('/mobile/push/register', {
        method:'POST', credentials:'include',
        headers:{'Content-Type':'application/json'},
        body:${JSON.stringify(payload)}
      }).then(function(response){ if(!response.ok) console.warn('Cadastro FCM pendente: HTTP '+response.status); }).catch(function(){ console.warn('Cadastro FCM nao disponivel.'); });
      return true;
    })(); true;`);
  }, []);

  useEffect(() => {
    let mounted = true;
    getPushToken().then(token => {
      if (!mounted || !token) return;
      pushToken.current = token;
      if (pageReady) registerInPortal();
    }).catch(() => {});
    return () => { mounted = false; };
  }, [pageReady, registerInPortal]);

  useEffect(() => {
    const sub = Notifications.addNotificationResponseReceivedListener(response => {
      const destination = safePushDestination(response.notification.request.content.data?.url);
      web.current?.injectJavaScript(`window.location.assign(${JSON.stringify(destination)}); true;`);
    });
    Notifications.getLastNotificationResponseAsync().then(response => {
      if (!response) return;
      const destination = safePushDestination(response.notification.request.content.data?.url);
      if (destination !== PORTAL) web.current?.injectJavaScript(`window.location.assign(${JSON.stringify(destination)}); true;`);
    }).catch(() => {});
    return () => sub.remove();
  }, []);

  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (canGoBack) { web.current?.goBack(); return true; }
      return false;
    });
    return () => sub.remove();
  }, [canGoBack]);

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar barStyle="dark-content" backgroundColor="#e1f0ea" />
      <WebView
        ref={web}
        source={{ uri: PORTAL }}
        javaScriptEnabled
        domStorageEnabled
        sharedCookiesEnabled
        thirdPartyCookiesEnabled={false}
        startInLoadingState
        renderLoading={() => <View style={styles.loading}><ActivityIndicator color="#087b65" /><Text style={styles.text}>Abrindo DISMEPE ONE...</Text></View>}
        onNavigationStateChange={nav => {
          setCanGoBack(nav.canGoBack);
          if (isPortalUrl(nav.url)) registerInPortal();
        }}
        onShouldStartLoadWithRequest={request => {
          if (isPortalUrl(request.url)) return true;
          if (/^https?:\/\//i.test(request.url)) Linking.openURL(request.url).catch(() => {});
          return false;
        }}
        onLoadEnd={() => { setPageReady(true); setError(''); registerInPortal(); }}
        onError={() => setError('Nao foi possivel acessar o DISMEPE ONE. Verifique sua conexao com a internet.')}
      />
      {error ? <View style={styles.banner}><Text style={styles.text}>{error}</Text></View> : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#e1f0ea' },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  text: { fontSize: 13, color: '#174735', textAlign: 'center' },
  banner: { padding: 9, backgroundColor: '#fff2e6' }
});
