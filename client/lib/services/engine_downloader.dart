// Engine downloader — downloads VPN binaries on first launch
//
// Downloads (in order):
//   1. Xray-core zip  → xray.exe + wintun.dll + geoip.dat + geosite.dat
//   2. tun2socks zip  → tun2socks.exe  (нужен для TUN-режима VLESS/Naive)
//   3. NaiveProxy zip → naive.exe
//   4. AmneziaWG MSI  → silent install → amneziawg.exe
//
// Each download has multiple fallback mirrors + 2 retries per mirror.
// Timeout per attempt: 90 seconds.

import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'package:archive/archive_io.dart';

class EngineDownloader {
  EngineDownloader._();
  static final EngineDownloader instance = EngineDownloader._();

  // ── Download URLs ──────────────────────────────────────────────────────────
  // PRIMARY: наш собственный GitHub release (engines-v1) — стабильно, без CDN-блокировок
  // FALLBACK: оригинальные источники + ghproxy зеркала
  static const _ownBase = 'https://github.com/JustMilkyArt/VPN-2/releases/download/engines-v1';

  static const _xrayUrls = [
    '$_ownBase/Xray-windows-64.zip',
    'https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-windows-64.zip',
    'https://mirror.ghproxy.com/https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-windows-64.zip',
    'https://ghproxy.net/https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-windows-64.zip',
  ];

  static const _tun2socksUrls = [
    '$_ownBase/tun2socks-windows-amd64.zip',
    'https://github.com/xjasonlyu/tun2socks/releases/download/v2.6.0/tun2socks-windows-amd64.zip',
    'https://mirror.ghproxy.com/https://github.com/xjasonlyu/tun2socks/releases/download/v2.6.0/tun2socks-windows-amd64.zip',
    'https://ghproxy.net/https://github.com/xjasonlyu/tun2socks/releases/download/v2.6.0/tun2socks-windows-amd64.zip',
  ];

  static const _naiveUrls = [
    '$_ownBase/naiveproxy-v148-win-x64.zip',
    'https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip',
    'https://mirror.ghproxy.com/https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip',
    'https://ghproxy.net/https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip',
  ];

  static const _awgMsiUrls = [
    '$_ownBase/amneziawg-amd64-2.0.0.msi',
    'https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi',
    'https://mirror.ghproxy.com/https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi',
    'https://ghproxy.net/https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi',
  ];

  static const _awgExePath = r'C:\Program Files\AmneziaWG\amneziawg.exe';

  // ── State notifiers ────────────────────────────────────────────────────────
  final ValueNotifier<DownloadState> state     = ValueNotifier(DownloadState.idle);
  final ValueNotifier<String>        statusText = ValueNotifier('');
  final ValueNotifier<double>        progress   = ValueNotifier(0.0);

  String? _cachedDir;

  /// Returns (and creates) the engines directory.
  Future<String> get enginesDir async {
    if (_cachedDir != null) return _cachedDir!;
    final appDir = await getApplicationSupportDirectory();
    final dir    = Directory(p.join(appDir.path, 'engines'));
    if (!dir.existsSync()) dir.createSync(recursive: true);
    _cachedDir = dir.path;
    return _cachedDir!;
  }

  /// Returns true when all required binaries + AWG are present.
  Future<bool> areEnginesReady() async {
    final dir = await enginesDir;
    for (final name in ['xray.exe', 'naive.exe', 'wintun.dll', 'tun2socks.exe']) {
      if (!File(p.join(dir, name)).existsSync()) return false;
    }
    // AWG is optional on first check — installed separately
    return true;
  }

  /// Returns true when AmneziaWG is installed.
  bool get isAwgInstalled => File(_awgExePath).existsSync();

  /// Main download — call on first launch.
  /// Downloads: xray, naive, AWG MSI (if not installed).
  Future<void> downloadAll() async {
    if (state.value == DownloadState.downloading) return;
    state.value    = DownloadState.downloading;
    progress.value = 0.0;

    try {
      final dir = await enginesDir;

      // ── Step 1: Xray-core (40%) ─────────────────────────────────────────
      final needXray    = !File(p.join(dir, 'xray.exe')).existsSync();
      final needWintun  = !File(p.join(dir, 'wintun.dll')).existsSync();
      final needGeoip   = !File(p.join(dir, 'geoip.dat')).existsSync();
      final needGeosite = !File(p.join(dir, 'geosite.dat')).existsSync();

      if (needXray || needWintun || needGeoip || needGeosite) {
        final bytes = await _downloadWithFallback(
          label: 'Xray-core',
          urls:  _xrayUrls,
          progressBase: 0.0,
          progressRange: 0.35,
        );
        _status('Распаковка Xray-core...');
        final archive = await compute(_decodeZip, bytes);
        for (final f in archive) {
          if (needXray    && f.name == 'xray.exe')    _write(f, dir, 'xray.exe');
          if (needWintun  && f.name == 'wintun.dll')  _write(f, dir, 'wintun.dll');
          if (needGeoip   && f.name == 'geoip.dat')   _write(f, dir, 'geoip.dat');
          if (needGeosite && f.name == 'geosite.dat') _write(f, dir, 'geosite.dat');
        }
        _status('Xray-core: ОК');
      } else {
        _status('Xray-core: уже установлен');
      }
      progress.value = 0.35;

      // ── Step 2: tun2socks (20%) ──────────────────────────────────────────
      if (!File(p.join(dir, 'tun2socks.exe')).existsSync()) {
        final bytes = await _downloadWithFallback(
          label: 'tun2socks',
          urls:  _tun2socksUrls,
          progressBase: 0.35,
          progressRange: 0.20,
        );
        _status('Распаковка tun2socks...');
        final archive = await compute(_decodeZip, bytes);
        for (final f in archive) {
          final n = f.name.toLowerCase();
          if (n.endsWith('tun2socks.exe') || n.endsWith('tun2socks-windows-amd64.exe')) {
            _write(f, dir, 'tun2socks.exe');
            break;
          }
        }
        _status('tun2socks: ОК');
      } else {
        _status('tun2socks: уже установлен');
      }
      progress.value = 0.55;

      // ── Step 3: NaiveProxy (15%) ─────────────────────────────────────────
      if (!File(p.join(dir, 'naive.exe')).existsSync()) {
        final bytes = await _downloadWithFallback(
          label: 'NaiveProxy',
          urls:  _naiveUrls,
          progressBase: 0.55,
          progressRange: 0.15,
        );
        _status('Распаковка NaiveProxy...');
        final archive = await compute(_decodeZip, bytes);
        for (final f in archive) {
          final n = f.name.toLowerCase();
          if (n.endsWith('naive.exe') || n.endsWith('naiveproxy.exe')) {
            _write(f, dir, 'naive.exe');
            break;
          }
        }
        _status('NaiveProxy: ОК');
      } else {
        _status('NaiveProxy: уже установлен');
      }
      progress.value = 0.70;

      // ── Step 4: AmneziaWG MSI (25%) ──────────────────────────────────────
      if (!isAwgInstalled) {
        final msiBytes = await _downloadWithFallback(
          label: 'AmneziaWG',
          urls:  _awgMsiUrls,
          progressBase: 0.70,
          progressRange: 0.20,
        );

        _status('Установка AmneziaWG...');
        progress.value = 0.90;

        // Сохраняем MSI во временную папку
        final tmpDir  = Directory.systemTemp;
        final msiFile = File(p.join(tmpDir.path, 'amneziawg-setup.msi'));
        await msiFile.writeAsBytes(msiBytes, flush: true);

        // Тихая установка
        final result = await Process.run(
          'msiexec',
          ['/i', msiFile.path, '/quiet', '/norestart', 'ALLUSERS=1'],
          runInShell: false,
        ).timeout(const Duration(minutes: 3));

        // Удаляем временный файл
        try { msiFile.deleteSync(); } catch (_) {}

        if (result.exitCode != 0) {
          throw Exception(
              'AmneziaWG установка завершилась с кодом ${result.exitCode}. '
              'Попробуйте запустить приложение от имени Администратора.');
        }

        if (!isAwgInstalled) {
          throw Exception(
              'AmneziaWG установлен, но файл не найден. '
              'Перезапустите приложение.');
        }

        _status('AmneziaWG: ОК');
      } else {
        _status('AmneziaWG: уже установлен');
      }
      progress.value = 1.0;

      state.value    = DownloadState.done;
      statusText.value = 'Все компоненты готовы';
    } catch (e) {
      state.value      = DownloadState.error;
      statusText.value = '$e';
    }
  }

  // ── Private: download with fallback mirrors ────────────────────────────────

  /// Tries each URL in [urls] in order. On each URL attempts up to 3 retries.
  /// Returns raw bytes on success, throws on all failures.
  Future<Uint8List> _downloadWithFallback({
    required String label,
    required List<String> urls,
    required double progressBase,
    required double progressRange,
  }) async {
    final errors = <String>[];

    for (final url in urls) {
      for (var attempt = 1; attempt <= 2; attempt++) {
        try {
          _status('Загрузка $label (попытка $attempt)...');
          if (attempt > 1) {
            _status('Загрузка $label (зеркало: ${Uri.parse(url).host})...');
          }
          final bytes = await _fetchUrl(
            url,
            onProgress: (received, total) {
              if (total > 0) {
                final frac = received / total;
                progress.value = progressBase + progressRange * 0.85 * frac;
              }
            },
          );
          progress.value = progressBase + progressRange * 0.90;
          return bytes;
        } catch (e) {
          errors.add('$url (попытка $attempt): $e');
          debugPrint('Download failed: $url — $e');
          // Small delay before retry
          await Future.delayed(const Duration(seconds: 2));
        }
      }
    }

    throw Exception(
        'Не удалось загрузить $label после ${urls.length * 2} попыток.\n'
        'Проверьте подключение к интернету и повторите.\n'
        'Последняя ошибка: ${errors.isNotEmpty ? errors.last : "неизвестно"}');
  }

  Future<Uint8List> _fetchUrl(
    String url, {
    required void Function(int received, int total) onProgress,
  }) async {
    final client = http.Client();
    try {
      final request  = http.Request('GET', Uri.parse(url));
      final response = await client.send(request).timeout(
        const Duration(seconds: 90),
        onTimeout: () => throw TimeoutException('Таймаут 90с для $url'),
      );

      if (response.statusCode != 200) {
        throw Exception('HTTP ${response.statusCode}');
      }

      final total    = response.contentLength ?? 0;
      var received   = 0;
      final chunks   = <int>[];

      await for (final chunk in response.stream.timeout(
        const Duration(seconds: 60),
        onTimeout: (sink) => sink.close(),
      )) {
        chunks.addAll(chunk);
        received += chunk.length;
        onProgress(received, total);
      }

      if (total > 0 && chunks.length < total * 0.9) {
        throw Exception('Неполная загрузка: получено ${chunks.length} из $total байт');
      }

      return Uint8List.fromList(chunks);
    } finally {
      client.close();
    }
  }

  // ── Zip helpers ────────────────────────────────────────────────────────────

  static Archive _decodeZip(Uint8List bytes) => ZipDecoder().decodeBytes(bytes);

  void _write(ArchiveFile f, String destDir, String destName) {
    File(p.join(destDir, destName)).writeAsBytesSync(f.content as List<int>);
  }

  void _status(String text) {
    statusText.value = text;
    debugPrint('[EngineDownloader] $text');
  }
}

enum DownloadState { idle, downloading, done, error }
