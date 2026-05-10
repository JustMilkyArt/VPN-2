// SetupScreen — shown on first launch while downloading VPN engines

import 'package:flutter/material.dart';
import '../services/engine_downloader.dart';
import 'home_screen.dart';

class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key});

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  @override
  void initState() {
    super.initState();
    _startDownload();
  }

  Future<void> _startDownload() async {
    final dl = EngineDownloader.instance;
    dl.state.addListener(_onStateChange);
    await dl.downloadAll();
  }

  void _onStateChange() {
    final dl = EngineDownloader.instance;
    if (dl.state.value == DownloadState.done) {
      dl.state.removeListener(_onStateChange);
      if (mounted) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const HomeScreen()),
        );
      }
    } else if (dl.state.value == DownloadState.error) {
      dl.state.removeListener(_onStateChange);
      // Stay on screen — show retry button
      setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0D0F14),
      body: Center(
        child: SizedBox(
          width: 420,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Logo
              Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [Color(0xFF4F8EF7), Color(0xFF7B61FF)],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: const Icon(
                  Icons.shield_rounded,
                  color: Colors.white,
                  size: 40,
                ),
              ),
              const SizedBox(height: 28),
              const Text(
                'MilkyVPN',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  letterSpacing: -0.5,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'Первый запуск — загрузка компонентов',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.45),
                  fontSize: 14,
                ),
              ),
              const SizedBox(height: 48),

              // Progress bar
              ValueListenableBuilder<double>(
                valueListenable: EngineDownloader.instance.progress,
                builder: (_, value, __) => Column(
                  children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(6),
                      child: LinearProgressIndicator(
                        value: value,
                        minHeight: 6,
                        backgroundColor:
                            Colors.white.withValues(alpha: 0.08),
                        valueColor: const AlwaysStoppedAnimation<Color>(
                          Color(0xFF4F8EF7),
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    Text(
                      '${(value * 100).toInt()}%',
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.3),
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),

              // Status text
              ValueListenableBuilder<String>(
                valueListenable: EngineDownloader.instance.statusText,
                builder: (_, text, __) {
                  final isError =
                      EngineDownloader.instance.state.value ==
                          DownloadState.error;
                  return Text(
                    text,
                    style: TextStyle(
                      color: isError
                          ? const Color(0xFFFF4D6D)
                          : const Color(0xFF888CA4),
                      fontSize: 13,
                    ),
                    textAlign: TextAlign.center,
                  );
                },
              ),

              // Retry button (only on error)
              ValueListenableBuilder<DownloadState>(
                valueListenable: EngineDownloader.instance.state,
                builder: (_, state, __) {
                  if (state != DownloadState.error) {
                    return const SizedBox(height: 48);
                  }
                  return Padding(
                    padding: const EdgeInsets.only(top: 24),
                    child: FilledButton.icon(
                      onPressed: () {
                        setState(() {});
                        _startDownload();
                      },
                      icon: const Icon(Icons.refresh_rounded, size: 18),
                      label: const Text('Повторить'),
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFF4F8EF7),
                        padding: const EdgeInsets.symmetric(
                            horizontal: 28, vertical: 14),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                      ),
                    ),
                  );
                },
              ),
            ],
          ),
        ),
      ),
    );
  }
}
