import 'dart:io';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:window_manager/window_manager.dart';
import 'services/vpn_provider.dart';
import 'services/tray_service.dart';
import 'services/vpn_engine.dart';
import 'services/engine_downloader.dart';
import 'screens/home_screen.dart';
import 'screens/setup_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Window setup (Windows only)
  if (Platform.isWindows) {
    await windowManager.ensureInitialized();
    const options = WindowOptions(
      size: Size(780, 540),
      minimumSize: Size(700, 480),
      center: true,
      title: 'MilkyVPN',
      titleBarStyle: TitleBarStyle.normal,
      backgroundColor: Color(0xFF0D0F14),
      skipTaskbar: false,
    );
    await windowManager.waitUntilReadyToShow(options, () async {
      await windowManager.show();
      await windowManager.focus();
    });
  }

  // Check if engines are ready (first launch detection)
  // needsSetup = true if xray/naive missing OR amneziawg not installed
  final dl = EngineDownloader.instance;
  final enginesReady = await dl.areEnginesReady() && dl.isAwgInstalled;

  runApp(MyApp(needsSetup: !enginesReady));
}

class MyApp extends StatefulWidget {
  final bool needsSetup;
  const MyApp({super.key, required this.needsSetup});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> with WindowListener {
  final VpnProvider _vpnProvider = VpnProvider();

  @override
  void initState() {
    super.initState();
    if (Platform.isWindows) {
      windowManager.addListener(this);
      _initTray();
    }
  }

  @override
  void dispose() {
    if (Platform.isWindows) {
      windowManager.removeListener(this);
    }
    VpnEngine.instance.disconnect();
    _vpnProvider.dispose();
    super.dispose();
  }

  Future<void> _initTray() async {
    await TrayService.instance.init();

    TrayService.instance.onShowWindow = () async {
      await windowManager.show();
      await windowManager.focus();
    };

    TrayService.instance.onConnectToggle = () {
      if (_vpnProvider.isConnected) {
        _vpnProvider.disconnect();
      } else {
        _vpnProvider.connect();
      }
    };

    TrayService.instance.onQuit = () async {
      await VpnEngine.instance.disconnect();
      await TrayService.instance.dispose();
      exit(0);
    };

    VpnEngine.instance.status.addListener(() {
      final status = VpnEngine.instance.status.value;
      final connName = _vpnProvider.selectedConnection?.name;
      TrayService.instance.updateStatus(status, connName);
    });
  }

  @override
  void onWindowClose() async {
    if (Platform.isWindows) {
      await windowManager.hide();
    }
  }

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<VpnProvider>.value(
      value: _vpnProvider,
      child: MaterialApp(
        title: 'MilkyVPN',
        debugShowCheckedModeBanner: false,
        theme: _buildTheme(),
        home: widget.needsSetup ? const SetupScreen() : const HomeScreen(),
      ),
    );
  }

  ThemeData _buildTheme() {
    return ThemeData(
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xFF4F8EF7),
        brightness: Brightness.dark,
        surface: const Color(0xFF141720),
      ),
      scaffoldBackgroundColor: const Color(0xFF0D0F14),
      fontFamily: 'Segoe UI',
      useMaterial3: true,
      dialogTheme: DialogThemeData(
        backgroundColor: const Color(0xFF1A1D27),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
        ),
      ),
      cardTheme: CardThemeData(
        color: const Color(0xFF141720),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
        ),
      ),
    );
  }
}
