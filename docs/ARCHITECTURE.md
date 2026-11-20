# 🏛️ Arquitetura do Sistema — Legacy PSCam Sensor

Este documento descreve detalhadamente a arquitetura do **Legacy PSCam Sensor**, a separação de responsabilidades entre seus módulos, o fluxo de dados em tempo real e o relacionamento com o hardware da **PlayStation 4 Camera** e com o processo do **Just Dance PC**.

---

## 🧩 Visão Geral da Arquitetura

O sistema é baseado em uma **arquitetura modular em pacotes**, onde cada etapa do processamento de vídeo, inteligência artificial, cinemática, interface de usuário e comunicação entre processos opera de forma isolada e desacoplada:

```
LegacyPSCam_Sensor/
├── main.py                     # Ponto de entrada (CLI dispatcher e inicializador)
├── test_suite.py               # Suíte de testes automatizados (14/14 suítes integradas)
├── config.json                 # Gerenciamento e persistência das configurações locais
├── THIRD_PARTY_NOTICES.md      # Avisos de direitos autorais, licenças e separação de IP do firmware
├── driver/
│   └── legacy_pscam_device.inf # Pacote INF associando o WinUSB.sys nativo da Microsoft à PS4 Camera
├── sensor/                     # Pacote do Motor de Rastreamento e Visão Computacional
│   ├── __init__.py             # Exports unificados da API do sensor
│   ├── ps4_backend/            # Backend Próprio em Espaço de Usuário (WinUSB) para PlayStation 4 Camera
│   │   ├── __init__.py         # Exports públicos do backend nativo
│   │   ├── constants.py        # IDs USB (0580/058A/058B), hashes SHA-1/SHA-256 e geometrias ISP
│   │   ├── winusb_bindings.py  # Bindings ctypes para winusb.dll, cfgmgr32.dll e Overlapped I/O
│   │   ├── firmware_manager.py # Cache, download HTTPS, validação SHA-1/SHA-256 e upload USB de 512B
│   │   ├── usb_device.py       # Ciclo de vida USB (Interfaces 0 e 1, Probe/Commit UVC, Auto-Exposure)
│   │   ├── frame_streamer.py   # Anel isócrono de 8 URBs (EP 0x81), depacketizer e demux de olhos
│   │   └── driver_installer.py # Verificação PnP e instalação/reparo via pnputil com UAC sob demanda
│   ├── camera_manager.py       # Descoberta, negociação DirectShow/WinUSB e captura assíncrona
│   ├── stereo_matcher.py       # Motor de Visão Estéreo (Retificação, Triangulação Esparsa 3D e Máscara Densa)
│   ├── pose_tracker.py         # Motor MediaPipe Pose e máscara anatômica 320x240
│   ├── pose_filters.py         # Filtros cinemáticos (HandAnchor, AdaptiveSmoother, SkeletonCalibrator, PTZ)
│   ├── virtual_phone.py        # Cliente WebSocket UbiArt (/smartphone), Calibrador Adaptativo e Acelerômetro 3D
│   ├── telemetry_benchmark.py  # Benchmark comparativo de telemetria (Câmera vs DS4), alinhamento temporal e ganho
│   ├── ds4_controller.py       # Driver Bluetooth/USB HID nativo DualShock 4 (500+ Hz, IMU, botões e vibração)
│   ├── kinect_emulator.py      # Emulador de Kinect na memória (detecção de processos e hot-patching IAT)
│   ├── kinect_shared_memory.py # Driver IPC com KinectBridge (JDP1 344B + JDP2 664B + JMI1/2 1.3MB + JXC1 28B)
│   ├── tracking_session.py     # Orquestrador do loop de rastreamento e eventos de teclado
│   ├── tracking_overlay.py     # Renderização visual do esqueleto, silhueta sombreada e HUD
│   └── config_manager.py       # Gerenciamento e persistência das configurações (config.json)
├── ui/                         # Pacote da Interface Gráfica
│   ├── __init__.py             # Exporta LegacySensorGUI, UIPagesMixin, widgets reutilizáveis e launch_app
│   ├── gui_qt.py               # Janela principal e controlador de eventos em PySide6 / Qt 6
│   ├── pages.py                # Construtores declarativos das 4 páginas Qt 6 (UIPagesMixin)
│   ├── widgets.py              # Componentes Qt 6 reutilizáveis (SlidingStackedWidget, DeviceNavCard, CalibPresetCard)
│   ├── benchmark_dialog.py     # Diálogo e gráfico 2D QPainter de benchmark comparativo (Câmera vs DS4)
│   ├── theme.py                # Paleta de cores, tipografia e presets
│   └── icons.py                # Gerador e renderizador de ícones vetoriais e supersampled
├── assets/                     # Recursos visuais e mídias
│   ├── icons/                  # Ícones SVG e PNG da aplicação
│   └── fonts/                  # Fontes TTF (Kanit, InterTight, NationalPark)
├── models/
│   ├── pose_landmarker_lite.task  # Modelo MediaPipe Pose Lite (Perfil Competitivo)
│   ├── pose_landmarker_full.task  # Modelo MediaPipe Pose Full (Perfil Equilibrado)
│   └── pose_landmarker_heavy.task # Modelo MediaPipe Pose Heavy (Perfil Ultra Estável)
└── tools/
    ├── Kinect10.dll               # DLL proxy de 32 bits para a pasta do Just Dance PC
    └── get_cameras.ps1            # Script PowerShell auxiliar para enumeração de câmeras WinRT
```

```mermaid
flowchart TD
    subgraph HARDWARE_LAYER["Camada de Entrada (Hardware)"]
        PS4CAM["PlayStation 4 Camera\n(OV580 Stereo @ 60 FPS)"]
        WEBCAM["Webcam USB / Integrada\n(UVC DirectShow)"]
        NATIVE_BACKEND["sensor.ps4_backend\n(Native WinUSB User-Space Engine)"]
        PS4CAM -->|USB 3.0 Isoch EP 0x81| NATIVE_BACKEND
    end

    subgraph INGESTION_LAYER["Camada de Ingestão e Captura (sensor/camera_manager.py)"]
        CAM_MGR["sensor.CameraManager\n(LatestFrameCamera)"]
        NATIVE_BACKEND -->|YUY2 -> BGR (Olho Direito Padrão)| CAM_MGR
        WEBCAM -->|BGR / DirectShow| CAM_MGR
    end

    subgraph VISION_LAYER["Camada de IA e Cinemática (sensor/pose_tracker.py)"]
        POSE_ENGINE["sensor.PoseTracker\n(MediaPipe PoseLandmarker)"]
        ANCHOR["HandAnchorFilter\n(Extrapolação de Antebraço)"]
        SMOOTHER["AdaptiveSmoother\n(EMA Anti-Jitter Dinâmico)"]
        CALIBRATOR["SkeletonCalibrator\n(Inversão X + Normalização)"]
        MASK_GEN["build_body_mask\n(Segmentação Anatômica)"]
        
        CAM_MGR -->|Frame BGR Bruto| POSE_ENGINE
        POSE_ENGINE --> ANCHOR
        ANCHOR --> SMOOTHER
        SMOOTHER --> CALIBRATOR
        POSE_ENGINE --> MASK_GEN
    end

    subgraph IPC_LAYER["Camada de IPC (sensor/kinect_shared_memory.py)"]
        BRIDGE["sensor.KinectBridge"]
        MEM_POSE["Local\\LegacyWebcamKinectPose\n(344B / JDP1)"]
        MEM_IMG["Local\\LegacyWebcamKinectImage\n(1.3MB / JMI1 & JMI2)"]
        MEM_COACH["Local\\LegacyWebcamKinectCoachX\n(28B / JXC1)"]
        
        CALIBRATOR -->|20 Joints| BRIDGE
        MASK_GEN -->|Máscara do Jogador| BRIDGE
        CAM_MGR -.->|Frame BGRA| BRIDGE
        
        BRIDGE --- MEM_POSE
        BRIDGE --- MEM_IMG
        BRIDGE --- MEM_COACH
    end

    subgraph GAME_LAYER["Camada do Jogo"]
        DLL["Kinect10.dll\n(Proxy Win32 no jogo)"]
        GAME["Just Dance PC\n(Legacy Offline Engine)"]
        MEM_POSE -->|NuiSkeletonGetNextFrame| DLL
        MEM_IMG -->|NuiImageStreamGetNextFrame| DLL
        DLL --> GAME
    end

    subgraph UI_LAYER["Camada de Apresentação (ui/ e assets/)"]
        GUI["ui.LegacySensorQtGUI\n(PySide6 / Qt 6 PlayStation Theme)"]
        OVERLAY["sensor.TrackingOverlay\n(Silhueta, Contorno e HUD)"]
        ASSETS["assets/icons/\n(Ícones Vetoriais)"]
        CAM_MGR -.->|Frame Espelhado| OVERLAY
        MASK_GEN -.->|Máscara Espelhada| OVERLAY
        CALIBRATOR -.->|Coordenadas 2D| OVERLAY
        ASSETS -.-> GUI
    end
```

---

## 📦 Responsabilidades dos Módulos

### 1. `main.py` — Despachante e Ponto de Entrada
- **Responsabilidade:** Inicialização da aplicação, parsing de parâmetros da linha de comando (`--start`, `--mode`, `--camera`) e carregamento da GUI ou da sessão de rastreamento direto.
- **Relações:** Instancia `ConfigManager` e aciona `ui.launch_app()` ou `tracking_session.py`.

### 2. `gui_qt.py` e `pages.py` — Interface do Usuário (Painel de Controle PlayStation em Qt 6)
- **Responsabilidade:** Interface visual moderna desenvolvida em **PySide6 (Qt 6)**, dividida entre o controlador principal de janela/eventos (`gui_qt.py`) e os construtores declarativos das 4 páginas de navegação (`pages.py` / `UIPagesMixin`). Conta com animações fluidas de transição entre abas (`SlidingStackedWidget`), layout dividido com barra lateral estilizada de seleção de dispositivo (PlayStation 4 Camera, Webcam Padrão e DualShock 4), abas superiores centralizadas ("Video Settings", "Calibration", "Controller Settings", "Experimental"), paleta oficial PlayStation Blue (`#00439C`), cards com sombras suaves e ícones vetoriais anti-aliased. Permite selecionar perfis de rastreamento (**Equilibrado**, **Competitivo**, **Ultra Estável**), conta com calibração automática e ajustes experimentais de Auto-Framing (FaceFollow PTZ) e Celular Virtual.
- **Ciclo de Vida do Driver e Hotplug Reativo:** Monitora a cada 1.0 segundo o hardware PnP e o ciclo de vida da PS4 Camera (`NOT_INSTALLED`, `DISCONNECTED`, `DRIVER_STOPPED`, `BOOTLOADER_UPLOADING`, `WAITING_VCAM`, `READY`).
- **Threading Não-Bloqueante:** Tanto a enumeração de câmeras do OpenCV quanto a sessão de rastreamento executam em threads assíncronas dedicadas, mantendo a janela do Qt 6 totalmente fluida a 60 FPS e sem congelamentos na UI.

### 3. `camera_manager.py` — Gerenciamento de Câmera e Captura Assíncrona
- **Classe `LatestFrameCamera`:** Executa um loop contínuo de captura de quadros em thread separada com um buffer atômico de profundidade 1 e contador monotônico de sequência (`frame_seq`). Com `read(only_new=True)`, o loop de rastreamento consome apenas quadros de hardware inéditos, eliminando 100% do reprocessamento de frames duplicados quando o loop roda mais rápido que a câmera.
- **Leitura Direta do FrameBus com Bypass DirectShow (`FrameBusReader`):** Conecta-se diretamente à memória compartilhada `Global\PSCam4Win{slot}.FrameBus` para ler frames `YUY2` sem cópias intermediárias. Quando o `FrameBus` já está ativo e transmitindo, o `LatestFrameCamera._open_and_negotiate()` ignora a negociação de 1 a 2 segundos da câmera virtual DirectShow (`cv2.VideoCapture`) e inicia a captura imediatamente, mantendo o DirectShow apenas como fallback preguiçoso (*lazy fallback*).
- **Snapshot Rápido de Hardware PnP (`get_hardware_snapshot`):** Utiliza diretamente a DLL nativa `cfgmgr32.dll` (`CM_Get_Device_ID_ListW`) com filtro de dispositivos presentes, retornando uma assinatura de hardware em menos de **3 milissegundos**, sem a sobrecarga de subprocessos como `pnputil`.
- **Máquina de Estados da PS4 Camera (`get_ps4_camera_state`):** Rastreia os IDs de hardware USB (`VID_05A9&PID_0580` do bootloader e `VID_05A9&PID_058B` do sensor ativo) e a contagem de câmeras virtuais (`SWD\VCAMDEVAPI`) para determinar o status exato da câmera.
- **Negociação de Formatos (FourCC):** Identifica a PlayStation 4 Camera (`is_pscam=True`) e preserva o stream nativo em **YUY2 / NV12**, evitando a definição forçada de `'MJPG'` que corrompe a negociação com a câmera virtual do driver.
- **Enumeração de Dispositivos:** Cruza os índices do OpenCV com a lista de dispositivos PnP do Windows (`Get-PnpDevice -Class Camera`) para exibir nomes amigáveis na interface.

### 4. `pose_tracker.py` e `pose_filters.py` — Motor de Pose e Cinemática
- **`PoseTracker`:** Inicializa e gerencia a rede neural `vision.PoseLandmarker` do Google MediaPipe no modo contínuo de vídeo (`RunningMode.VIDEO`), preservando as proporções nativas de aspecto da câmera e operando com limiares otimizados (`det_c <= 0.45`, `pres_c <= 0.35`) para garantir detecção contínua e sem perda de rastreamento.
- **Pré-Downscaling In-Place para Quadros de Alta Resolução (`>640px`):** Para streams HD como `1280x800` (PS4 Camera) ou `1920x1080` (Webcams Full HD), redimensiona in-place em buffers pré-alocados (`_infer_bgr` e `_infer_rgb`, ex.: `640x400` ou `640x360`) antes de enviar ao MediaPipe, reduzindo em 4x o custo de conversão RGB e de alocação da máscara de segmentação neural, enquanto mantém os quadros originais em resolução total (`1280x800`) para a triangulação estéreo sub-pixel (`StereoDepthEngine`).
- **Garantia de Monotonicidade:** Força que `timestamp_ms` seja estritamente incremental a cada frame (`timestamp_ms = max(now_ms, last_ms + 1)`), prevenindo quebras em 60 FPS estáveis.
- **Sintetizador de Membros Inferiores:** Quando o jogador está diante de uma mesa ou notebook e a câmera não enquadra quadris ou pernas, sintetiza quadris com confiança >= 0.45 (`TRACKED`) e pernas naturais eretas com confiança 0.35 (`INFERRED`), impedindo que o `Kinect10.dll` perca o jogador.
- **`HandAnchorFilter`:** Detecta quando a mão perde confiança e extrapola a posição ao longo do vetor anatômico do antebraço (`cotovelo -> pulso`), garantindo que giros de mão não percam pontos nas coreografias.
- **`AdaptiveSmoother` Independente de FPS (`dt`-Normalized 3D & 2D):** Filtro de Média Móvel Exponencial (EMA) com velocidade 3D e 2D normalizada pelo delta de tempo (`dt` relativo à referência de `1/30s`). Suaviza tanto o esqueleto 3D enviado ao Just Dance PC (`apply`) quanto o esqueleto 2D renderizado na janela de preview (`apply_pixel`), garantindo resposta idêntica e livre de jitter em 30 FPS e 60 FPS.
- **`SkeletonCalibrator` Multi-Tier:** Opera em 3 níveis adaptativos:
  1. *Tier 1 (Corpo Inteiro / `full_body`):* Cabeça a tornozelos.
  2. *Tier 2 (Meio Corpo / `flexible_torso`):* Cabeça a quadris com proporção áurea.
  3. *Tier 3 (Enquadramento Mesa / `upper_body`):* Cabeça a ombros e envergadura biacromial, com ancoragem de quadril virtual em `Y = 1.0m`.
- **Ancoragem Métrica de Altura do Quadril (`Y = 1.0m`):** Mantém a convenção métrica nativa do Kinect v1 exigida pelo Just Dance PC (`hip_height_m: 1.0`), posicionando quadris em 1.0m, cabeça em 1.75m e pés no chão em 0.10m.
- **Rastreador de Espaço de Câmera (`CameraSpaceXTracker` & `apply_slot_snap`):** Mapeia o deslocamento horizontal do jogador na sala para a faixa lateral do palco de $\pm 1.4\text{m}$, permitindo transitar com precisão e sem travamento entre todos os 6 slots de dançarinos.
- **Ordem Ótima do Pipeline:** O esqueleto anatômico é suavizado pelo `AdaptiveSmoother` *antes* da translação lateral de sala e do encaixe de slots. Isso assegura que o filtro EMA não restrinja nem atrase a seleção dinâmica de dançarinos.
- **`build_body_mask` Nativo em `320x240`:** Gera e aplica o fechamento morfológico da máscara de segmentação anatômica diretamente na resolução nativa do Kinect (`320x240`), reduzindo em 13x o custo de CPU em câmeras `1280x800` e fundindo via bitwise-OR com a segmentação neural do MediaPipe.

### 5. `tracking_session.py` — Orquestrador do Loop de Rastreamento
- **Responsabilidade:** Conecta todos os módulos durante o jogo:
  1. Abre a câmera via `LatestFrameCamera`.
  2. Inicializa o `PoseTracker` e o `KinectBridge`.
  3. No loop principal, aguarda apenas frames novos da câmera (`camera.read(only_new=True)`), processa o frame bruto na IA, grava os 20 joints e a máscara de imagem no `KinectBridge`, gera o frame espelhado com overlay visual (silhueta, contorno e esqueleto) e bombeia eventos de teclado (`cv2.waitKey(1)`).
  4. Trata atalhos: `[C]` Recalibrar, `[M]` Alternar espelhamento, `[H]` Ocultar HUD, `[Q/ESC]` Sair.
  5. Fecha e desaloca os recursos de forma limpa ao encerrar.

### 6. `tracking_overlay.py` — Renderizador de HUD, Silhueta e Esqueleto
- **Responsabilidade:** 
  1. `draw_player_silhouette`: Extrai os contornos da máscara `320x240`, escala os vértices para a resolução do frame de preview e aplica `cv2.addWeighted` exclusivamente dentro da *Bounding Box* (ROI) do jogador, eliminando cópias de frame inteiro a 60 FPS.
  2. `draw_skeleton`: Desenha os nós articulares e os ossos com gradiente de cores.
  3. `draw_hud`: Exibe os banners superior e inferior usando fatias de ROI in-place com contadores reais de FPS da câmera e da inferência, status do canal IPC e atalhos de teclado.

### 7. `kinect_shared_memory.py` — Ponte IPC Multi-Canal (`KinectBridge`)
- **Responsabilidade:** Gerencia os três canais de memória mapeada consumidos pelo `Kinect10.dll`:
  1. `KinectSharedMemory` (`Local\LegacyWebcamKinectPose`, 344 bytes, `JDP1`): Coordenadas e confiança das 20 articulações corporais.
  2. `KinectImageSharedMemory` (`Local\LegacyWebcamKinectImage` JMI1 e `Local\LegacyWebcamKinectImageV2` JMI2, 1.305.632 bytes): Frame de vídeo BGRA 640x480 e máscara de jogador 320x240 (player index mask) para a silhueta no HUD do jogo e seleção de dançarinos. Alimentado com máscara anatômica compatível com o limiar de 64 (0x40) do `Kinect10.dll`.
  3. `KinectCoachXSharedMemory` (`Local\LegacyWebcamKinectCoachX`, 28 bytes, `JXC1`): Posição horizontal do coach.
- **Protocolo Seqlock:** Todos os canais implementam escrita atômica lockless (ímpar durante escrita, par ao finalizar), garantindo leituras consistentes pelo Just Dance PC sem travar threads.

### 8. `config_manager.py` — Persistência de Configurações
- **Responsabilidade:** Lê, valida e grava as preferências do usuário no arquivo `config.json`. Oferece fallbacks robustos caso o arquivo seja corrompido ou inacessível.

### 9. `ds4_controller.py` — Driver Nativo DualShock 4 & Controles Compatíveis (Nível A) Bluetooth/USB HID
- **Responsabilidade:** Comunicação direta de ultra-alta frequência via Win32 SetupAPI e HID com controles Sony DualShock 4, controles licenciados de terceiros (Hori, Nacon, Razer, Astro, Scuf) e réplicas/clones com chipsets comuns (ShanWan, DragonRise) conectados por Bluetooth ou USB:
  1. Suporta nativamente relatórios padrão `0x01` (64 bytes) e relatórios estendidos `0x11` (78 bytes).
  2. Suporte adaptativo de Output Report para vibração háptica (rumble) e lightbar RGB (`32 bytes` report `0x05` ou `78 bytes` report `0x11` com CRC-32).
  3. Desacoplamento total de hardware de câmera durante o modo de controle.
  4. Mapeamento de 3 eixos de aceleração diretamente para o protocolo de pontuação do Just Dance PC através do `virtual_phone.py`.
  5. Modo Permissivo com identificação amigável do modelo (`detect_controller_name`) e bloqueio preventivo de gamepads Xbox.
  6. Diagnóstico contínuo de integridade do sensor de aceleração (`imu_frozen`) para sinalizar réplicas que necessitam de conexão cabeada USB.

### 10. `virtual_phone.py` — Emulador de Celular UbiArt Just Dance Controller & Calibração Adaptativa
- **Responsabilidade:** Emula um smartphone conectado via WebSocket local (`/smartphone`), permitindo dançar músicas que exigem controle de mão tanto por visão computacional da mão quanto via hardware físico (DualShock 4).
- **Auto-Detecção Multi-Versão:** Descoberta via UDP 6000/7000 com prioridade localhost (127.0.0.1) e negociação de subprotocolo estrito:
  - `v2.phonescoring.jd.ubisoft.com` com WSS/TLS para Just Dance 2020–2022.
  - `v1.phonescoring.jd.ubisoft.com` com WS plain TCP para Just Dance 2017/2018 Legacy Offline.
- **Rastreamento de Música e Ciclo de Vida:** Extração de `mapName` do pacote `JD_PhoneUiSetupData` e monitoramento de ativação de pontuação (`JD_EnableScoringPhoneData`) para disparo de auto-gravação (`logs/[mapName]_[source]_[timestamp].csv`).
- **Motor Adaptativo (`AdaptiveCalibrationTuner`):** Monitora eventos de feedback de dança (*PERFECT*, *GOOD*, *OK*, *MISS*) em tempo de execução e calibra o ganho da sensibilidade dinamicamente.

### 11. `telemetry_benchmark.py` — Benchmark Comparativo (Câmera vs DualShock 4)
- **Responsabilidade:** Processamento pós-dança de séries temporais de aceleração:
  1. Parsing de arquivos CSV de telemetria nos formatos legado (10 colunas) e estendido (13 colunas).
  2. Alinhamento temporal preciso via correlação cruzada (*cross-correlation*) e reamostragem a 60 Hz.
  3. Cálculo de métricas comparativas: correlação de Pearson, atraso/latência média em milissegundos, picos G e P95.
  4. Cálculo matemático do ganho de sensibilidade sugerido para equiparar a curva da câmera à aceleração real do acelerômetro de hardware.
  5. Agrupamento de sessões prontas na pasta `logs/` para exibição instantânea no `TelemetryBenchmarkDialog`.
  6. *Nota de UI:* Módulo e caixas de diálogo preservados de forma íntegra no backend, porém desabilitados por padrão (`benchmark_auto_record: false`) e desacoplados da interface gráfica Qt 6 (`gui_qt.py`) para manter a experiência enxuta.

---

## 🎮 Integração de Hardware: PlayStation 4 Camera (OV580 — Backend Nativo WinUSB)

A PlayStation 4 Camera (incluindo a versão **PlayStation 4 Camera Slim** CUH-ZEY2 e CUH-ZEY1) utiliza o controlador **OmniVision OV580** acoplado a dois sensores estéreo **OmniVision OV9713**.

```
[ PS4 Camera (USB 3.0) ]
        │
        ▼ (VID: 0x05A9, PID: 0x0580 - Bootloader sem firmware)
[ sensor.ps4_backend.PS4FirmwareManager ]
        │  1. Valida SHA-1/SHA-256 (%ProgramData%\LegacySensor\Firmware\firmware.bin)
        │  2. Envia 68.032 bytes em blocos de 512B via WinUsb_ControlTransfer + Reboot (0x5B)
        ▼ (VID: 0x05A9, PID: 0x058B - Composite Video MI_00)
[ sensor.ps4_backend.PS4UsbDevice + PS4CameraBackend ]
        │  3. Abre Interfaces 0 (VideoControl) e 1 (VideoStreaming Alt 1)
        │  4. Executa UVC Probe/Commit (YUY2 1280x800 @ 60 FPS) + Auto-Exposure (CT_AE_MODE=0x02)
        │  5. Mantém anel isócrono de 8 URBs (WinUsb_ReadIsochPipeAsap) no Endpoint 0x81
        │  6. Desempacota linhas de 3448 px e separa Olho Esquerdo (@96B) e Olho Direito (@2656B)
        ▼
[ LatestFrameCamera (sensor/camera_manager.py) ]
        │  7. Entrega o Olho Direito por padrão (ou Olho Esquerdo) em BGR ao PoseTracker
```

1. **Autossuficiência em Espaço de Usuário:** O `LegacyPSCam_Sensor` gerencia todo o ciclo de vida da câmera diretamente sobre o driver oficial `WinUSB.sys` da Microsoft via `winusb.dll`, sem depender de processos externos, aplicativos de bandeja ou câmeras virtuais.
2. **Gerenciamento Criptográfico de Firmware:** O arquivo `firmware.bin` (68.032 bytes, SHA-1 `8b8a6621d358f6782c2e3b31aac2cdfb25102c00`) é armazenado em `%ProgramData%\LegacySensor\Firmware\` e carregado automaticamente a cada nova conexão física.
3. **Seleção de Olho e Preparação Estéreo:** Ambos os sensores OV9713 (Esquerdo e Direito) são extraídos e mantidos sincronizados com seus timestamps PTS de hardware, entregando o **Olho Direito** por padrão ao pipeline de tracking e permitindo alternância em tempo real para o Olho Esquerdo.
