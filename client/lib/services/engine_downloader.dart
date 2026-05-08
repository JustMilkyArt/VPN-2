// Engine downloader — downloads VPN binaries on first launch
//
// Downloads:
//   Xray-core zip → xray.exe + wintun.dll + geoip.dat + geosite.dat
//   NaiveProxy zip → naive.exe
//
// AmneziaWG is installed separately via MSI (handled in VpnEngine).
// tun2socks is NOT needed (we use system proxy instead).

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

  // Download URLs (verified May 2026)
  static const _xrayUrl =
      'https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-windows-64.zip';
  // NaiveProxy — klzgrad build for Windows x64
  static const _naiveUrl =
      'https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip';

  final ValueNotifier<DownloadState> state    = ValueNotifier(DownloadState.idle);
  final ValueNotifier<String>        statusText = ValueNotifier('');
  final ValueNotifier<double>        progress  = ValueNotifier(0.0);

  String? _enginesDir;

  /// Returns (and creates) the engines directory path.
  Future<String> get enginesDir async {
    if (_enginesDir != null) return _enginesDir!;
    final appDir = await getApplicationSupportDirectory();
    final dir    = Directory(p.join(appDir.path, 'engines'));
    if (!dir.existsSync()) dir.createSync(recursive: true);
    _enginesDir = dir.path;
    return _enginesDir!;
  }

  /// Returns true when all required binaries are present.
  Future<bool> areEnginesReady() async {
    final dir      = await enginesDir;
    final required = ['xray.exe', 'naive.exe', 'wintun.dll'];
    for (final name in required) {
      if (!File(p.join(dir, name)).existsSync()) return false;
    }
    return true;
  }

  /// Downloads missing binaries. Shows progress via [state] / [statusText] / [progress].
  Future<void> downloadAll() async {
    if (state.value == DownloadState.downloading) return;
    state.value   = DownloadState.downloading;
    progress.value = 0.0;

    try {
      final dir = await enginesDir;

      // ── 1. Xray-core (also contains wintun.dll + geo data) ──────────────
      final xrayMissing    = !File(p.join(dir, 'xray.exe')).existsSync();
      final wintunMissing  = !File(p.join(dir, 'wintun.dll')).existsSync();
      final geoipMissing   = !File(p.join(dir, 'geoip.dat')).existsSync();
      final geositeMissing = !File(p.join(dir, 'geosite.dat')).existsSync();

      if (xrayMissing || wintunMissing || geoipMissing || geositeMissing) {
        await _downloadAndExtract(
          label:         'Xray-core',
          url:           _xrayUrl,
          destDir:       dir,
          progressBase:  0.0,
          progressRange: 0.50,
          extract: (archive, destDir) {
            for (final f in archive) {
              if (xrayMissing    && f.name == 'xray.exe')    _writeFile(f, destDir, 'xray.exe');
              if (wintunMissing  && f.name == 'wintun.dll')  _writeFile(f, destDir, 'wintun.dll');
              if (geoipMissing   && f.name == 'geoip.dat')   _writeFile(f, destDir, 'geoip.dat');
              if (geositeMissing && f.name == 'geosite.dat') _writeFile(f, destDir, 'geosite.dat');
            }
          },
        );
      } else {
        statusText.value = 'Xray-core: уже установлен';
        progress.value   = 0.50;
      }

      // ── 2. NaiveProxy ─────────────────────────────────────────────────────
      if (!File(p.join(dir, 'naive.exe')).existsSync()) {
        await _downloadAndExtract(
          label:         'NaiveProxy',
          url:           _naiveUrl,
          destDir:       dir,
          progressBase:  0.50,
          progressRange: 0.50,
          extract: (archive, destDir) {
            for (final f in archive) {
              final name = f.name.toLowerCase();
              if (name.endsWith('naive.exe') || name.endsWith('naiveproxy.exe')) {
                _writeFile(f, destDir, 'naive.exe');
                break;
              }
            }
          },
        );
      } else {
        statusText.value = 'NaiveProxy: уже установлен';
        progress.value   = 1.0;
      }

      state.value    = DownloadState.done;
      statusText.value = 'Все компоненты готовы';
      progress.value  = 1.0;
    } catch (e) {
      state.value    = DownloadState.error;
      statusText.value = 'Ошибка: $e';
    }
  }

  // ── Private helpers ────────────────────────────────────────────────────────

  Future<void> _downloadAndExtract({
    required String label,
    required String url,
    required String destDir,
    required double progressBase,
    required double progressRange,
    required void Function(Archive, String) extract,
  }) async {
    statusText.value = 'Скачиваю $label...';
    progress.value   = progressBase;

    final client = http.Client();
    try {
      final request  = http.Request('GET', Uri.parse(url));
      final response = await client.send(request);

      if (response.statusCode != 200) {
        throw Exception('HTTP ${response.statusCode} для $label');
      }

      final total    = response.contentLength ?? 0;
      var received   = 0;
      final bytes    = <int>[];

      await for (final chunk in response.stream) {
        bytes.addAll(chunk);
        received += chunk.length;
        if (total > 0) {
          progress.value = progressBase + progressRange * 0.80 * (received / total);
        }
      }

      statusText.value = 'Распаковываю $label...';
      progress.value   = progressBase + progressRange * 0.85;

      final archive = await compute(_decodeZip, Uint8List.fromList(bytes));
      extract(archive, destDir);

      statusText.value = '$label: ОК';
      progress.value   = progressBase + progressRange;
    } finally {
      client.close();
    }
  }

  static Archive _decodeZip(Uint8List bytes) => ZipDecoder().decodeBytes(bytes);

  void _writeFile(ArchiveFile f, String destDir, String destName) {
    File(p.join(destDir, destName))
        .writeAsBytesSync(f.content as List<int>);
  }
}

enum DownloadState { idle, downloading, done, error }
