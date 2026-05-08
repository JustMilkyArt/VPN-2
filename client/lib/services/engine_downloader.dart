// Engine downloader — downloads VPN binaries on first launch
// Downloads: xray.exe, naive.exe, wintun.dll, awg-quick.exe (from AmneziaWG)

import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'package:archive/archive_io.dart';

class EngineDownloader {
  EngineDownloader._();
  static final EngineDownloader instance = EngineDownloader._();

  // Download URLs
  static const _xrayUrl =
      'https://github.com/XTLS/Xray-core/releases/download/v25.4.30/Xray-windows-64.zip';
  static const _wintunUrl =
      'https://www.wintun.net/builds/wintun-0.14.1.zip';
  static const _naiveUrl =
      'https://github.com/klzgrad/naiveproxy/releases/download/v130.0.6723.91-3/naiveproxy-v130.0.6723.91-3-win-x64.zip';
  static const _awgUrl =
      'https://github.com/amnezia-vpn/amneziawg-go/releases/download/v0.2.12/awg-windows-amd64.zip';

  final ValueNotifier<DownloadState> state =
      ValueNotifier(DownloadState.idle);
  final ValueNotifier<String> statusText = ValueNotifier('');
  final ValueNotifier<double> progress = ValueNotifier(0.0);

  String? _enginesDir;

  Future<String> get enginesDir async {
    if (_enginesDir != null) return _enginesDir!;
    final appDir = await getApplicationSupportDirectory();
    final dir = Directory(p.join(appDir.path, 'engines'));
    if (!dir.existsSync()) dir.createSync(recursive: true);
    _enginesDir = dir.path;
    return _enginesDir!;
  }

  // Check if all required binaries exist
  Future<bool> areEnginesReady() async {
    final dir = await enginesDir;
    final required = ['xray.exe', 'naive.exe', 'wintun.dll'];
    for (final name in required) {
      if (!File(p.join(dir, name)).existsSync()) return false;
    }
    return true;
  }

  // Main download method — call on first launch
  Future<void> downloadAll() async {
    if (state.value == DownloadState.downloading) return;
    state.value = DownloadState.downloading;
    progress.value = 0.0;

    try {
      final dir = await enginesDir;

      // 1. Xray
      if (!File(p.join(dir, 'xray.exe')).existsSync()) {
        await _downloadAndExtract(
          label: 'Xray-core',
          url: _xrayUrl,
          destDir: dir,
          extract: (archive, destDir) {
            for (final f in archive) {
              if (f.name.endsWith('xray.exe') && !f.name.contains('/')) {
                _extractFile(f, destDir, 'xray.exe');
                break;
              }
              // Some zips have it at root
              if (f.name == 'xray.exe') {
                _extractFile(f, destDir, 'xray.exe');
                break;
              }
            }
          },
          progressBase: 0.0,
          progressRange: 0.3,
        );
      } else {
        statusText.value = 'Xray-core: already present';
        progress.value = 0.3;
      }

      // 2. WinTUN
      if (!File(p.join(dir, 'wintun.dll')).existsSync()) {
        await _downloadAndExtract(
          label: 'WinTUN',
          url: _wintunUrl,
          destDir: dir,
          extract: (archive, destDir) {
            for (final f in archive) {
              // wintun/bin/amd64/wintun.dll
              if (f.name.toLowerCase().contains('amd64') &&
                  f.name.toLowerCase().endsWith('wintun.dll')) {
                _extractFile(f, destDir, 'wintun.dll');
                break;
              }
            }
          },
          progressBase: 0.3,
          progressRange: 0.2,
        );
      } else {
        statusText.value = 'WinTUN: already present';
        progress.value = 0.5;
      }

      // 3. NaiveProxy
      if (!File(p.join(dir, 'naive.exe')).existsSync()) {
        await _downloadAndExtract(
          label: 'NaiveProxy',
          url: _naiveUrl,
          destDir: dir,
          extract: (archive, destDir) {
            for (final f in archive) {
              if (f.name.toLowerCase().endsWith('naive.exe') ||
                  f.name.toLowerCase().endsWith('naiveproxy.exe')) {
                _extractFile(f, destDir, 'naive.exe');
                break;
              }
            }
          },
          progressBase: 0.5,
          progressRange: 0.25,
        );
      } else {
        statusText.value = 'NaiveProxy: already present';
        progress.value = 0.75;
      }

      // 4. AWG (awg-quick.exe)
      if (!File(p.join(dir, 'awg-quick.exe')).existsSync()) {
        await _downloadAndExtract(
          label: 'AmneziaWG',
          url: _awgUrl,
          destDir: dir,
          extract: (archive, destDir) {
            for (final f in archive) {
              if (f.name.toLowerCase().endsWith('.exe')) {
                _extractFile(f, destDir, 'awg-quick.exe');
                break;
              }
            }
          },
          progressBase: 0.75,
          progressRange: 0.25,
        );
      } else {
        statusText.value = 'AmneziaWG: already present';
        progress.value = 1.0;
      }

      state.value = DownloadState.done;
      statusText.value = 'All engines ready';
      progress.value = 1.0;
    } catch (e) {
      state.value = DownloadState.error;
      statusText.value = 'Error: $e';
    }
  }

  Future<void> _downloadAndExtract({
    required String label,
    required String url,
    required String destDir,
    required void Function(Archive, String) extract,
    required double progressBase,
    required double progressRange,
  }) async {
    statusText.value = 'Downloading $label...';
    progress.value = progressBase;

    final client = http.Client();
    try {
      final request = http.Request('GET', Uri.parse(url));
      final response = await client.send(request);

      if (response.statusCode != 200) {
        throw Exception('HTTP ${response.statusCode} for $label');
      }

      final totalBytes = response.contentLength ?? 0;
      var receivedBytes = 0;
      final bytes = <int>[];

      await for (final chunk in response.stream) {
        bytes.addAll(chunk);
        receivedBytes += chunk.length;
        if (totalBytes > 0) {
          final dlProgress = receivedBytes / totalBytes;
          progress.value = progressBase + progressRange * 0.8 * dlProgress;
        }
      }

      statusText.value = 'Extracting $label...';
      progress.value = progressBase + progressRange * 0.85;

      // Decode zip in isolate to avoid UI freeze
      final archive = await compute(_decodeZip, Uint8List.fromList(bytes));
      extract(archive, destDir);

      statusText.value = '$label: OK';
      progress.value = progressBase + progressRange;
    } finally {
      client.close();
    }
  }

  static Archive _decodeZip(Uint8List bytes) {
    return ZipDecoder().decodeBytes(bytes);
  }

  void _extractFile(ArchiveFile f, String destDir, String destName) {
    final outFile = File(p.join(destDir, destName));
    final data = f.content as List<int>;
    outFile.writeAsBytesSync(data);
  }
}

enum DownloadState { idle, downloading, done, error }
