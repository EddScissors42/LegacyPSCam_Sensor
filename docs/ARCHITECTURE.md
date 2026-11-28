# 🏛️ Arquitetura do Sistema — Legacy PSCam Sensor

Este documento descreve detalhadamente a arquitetura do **Legacy PSCam Sensor**, a separação de responsabilidades entre seus módulos, o fluxo de dados em tempo real e o relacionamento com o hardware da **PlayStation 4 Camera** e com o processo do **Just Dance PC**.

---

## 🧩 Visão Geral da Arquitetura

O sistema é baseado em uma **arquitetura modular em pacotes**, onde cada etapa do processamento de vídeo, inteligência artificial, cinemática, interface de usuário e comunicação entre processos opera de forma isolada e desacoplada:

```
LegacyPSCam_Sensor/
├── main.py                     # Ponto de entrada (CLI dispatcher e inicializador)
├── test_suite.py               # Suíte de testes automatizados isolados (19/19 suítes integradas + tests/)
├── tests/                      # Suíte modular unittest (tracking_math, controllers_and_cli)
├── config.json                 # Template local de configurações (persistência real em %APPDATA%)
├── THIRD_PARTY_NOTICES.md      # Avisos de direitos autorais, licenças e separação de IP do firmware
├── driver/
│   └── legacy_pscam_device.inf # Pacote INF associando o WinUSB.sys nativo da Microsoft à PS4 Camera
├── sensor/                     # Pacote do Motor de Rastreamento e Visão Computacional
│   ├── __init__.py             # Exports unificados da API do sensor
│   ├── session_logger.py       # Subsistema de log de sessão e telemetria de dança (CSV thread-safe e diagnóstico)
│   ├── ps4_backend/            # Backend Próprio em Espaço de Usuário (WinUSB) para PlayStation 4 Camera
│   │   ├── __init__.py         # Exports públicos do backend nativo
│   │   ├── constants.py        # IDs USB (0580/058A/058B), hashes SHA-1/SHA-256 e geometrias ISP
│   │   ├── winusb_bindings.py  # Bindings ctypes para winusb.dll, cfgmgr32.dll e Overlapped I/O
│   │   ├── firmware_manager.py # Cache, download HTTPS, validação SHA-1/SHA-256 e upload USB de 512B
│   │   ├── usb_device.py       # Ciclo de vida USB (Interfaces 0 e 1, Probe/Commit UVC, Auto-Exposure)
│   │   ├── frame_streamer.py   # Anel isócrono de 8 URBs (EP 0x81), depacketizer e demux de olhos
│   │   └── driver_installer.py # Verificação PnP e instalação/reparo via pnputil com UAC sob demanda
│   ├── camera_manager.py       # Descoberta, máquina de estados PS4 Camera e fachada de re-export
│   ├── camera_win32.py         # Interop Win32 ctypes (CfgMgr32 PnP <3ms, SetupAPI ~3ms, Toolhelp32 e UAC)
│   ├── framebus_reader.py      # Leitor IPC seqlock de memória compartilhada PSCam4Win (FrameBus YUY2 -> BGR)
│   ├── camera_capture.py       # LatestFrameCamera: captura assíncrona multi-backend (Phone, PS4 WinUSB, FrameBus, DirectShow)
│   ├── stereo_matcher.py       # Motor de Visão Estéreo (Retificação, Triangulação Esparsa 3D e Máscara Densa)
│   ├── pose_tracker.py         # Motor MediaPipe Pose (1P & 2P) e despacho por slot
│   ├── body_mask.py            # Geometria pura da máscara anatômica 320x240 e projeção 2D de 20 joints
│   ├── model_manager.py        # Gerenciador persistente de modelos .task em %APPDATA%\models (SHA-256 + download sob demanda)
│   ├── player_reid.py          # Memória de identidade anti-swap (AppearanceSignature, LongTermIdentityProfile, MultiPlayerAssociator) e Pose NMS
│   ├── player_slot.py          # Estado por jogador (PlayerSlotState), pipeline 20 joints e compositor de máscara indexada (com re-exports de player_reid)
│   ├── pose_filters.py         # Filtros cinemáticos (HandAnchor, AdaptiveSmoother, SkeletonCalibrator, Smart Body PTZ)
│   ├── person_lock.py          # Subsistema modular Person Lock-In (InertialCoastingFilter, DancerIdentityLock)
│   ├── gesture_detector.py     # Reconhecimento de gesto de braço levantado (ENTER em 1P e 2P)
│   ├── phone_camera.py         # Servidor WebApp HTTPS/WSS para câmera de smartphone via Wi-Fi
│   ├── qr_encoder.py           # Codificador QR Code ISO/IEC 18004 puro em Python (GF(256) + Pillow)
│   ├── tls_manager.py          # Gerador de certificados TLS X.509v3 autoassinados em ASN.1 DER puro
│   ├── psmove_shared_memory.py # Ponte IPC seqlock (Local\LegacyPSMoveState, PSM1 128B) e codificador ZCM2 49B
│   ├── telemetry_benchmark.py  # Utilitários de benchmark comparativo de telemetria CSV e alinhamento temporal
│   ├── ds4_controller.py       # Driver Bluetooth/USB HID nativo DualShock 4 (500+ Hz, IMU -> PS Move ZCM2, RGB & vibração)
│   ├── kinect_emulator.py      # Emulador in-memory de Kinect (Legacy10*.dll) e PS Move (LegacyMove*.dll) para x86 e x64
│   ├── kinect_shared_memory.py # Driver IPC singleton KinectBridge (JDP1 344B + JDP2 664B + JMI1/2 1.3MB + JXC1 28B)
│   ├── tracking_session.py     # Orquestrador do loop de rastreamento (1P/2P) e eventos de teclado
│   ├── tracking_overlay.py     # Renderização visual do esqueleto (P1 Azul / P2 Laranja Claro), silhueta e HUD
│   └── config_manager.py       # Gerenciamento de configurações e resolução de caminhos (%APPDATA% / logs / portable)
├── ui/                         # Pacote da Interface Gráfica
│   ├── __init__.py             # Exporta LegacySensorGUI, UIPagesMixin, widgets reutilizáveis e launch_app
│   ├── gui_qt.py               # Casca principal da janela em PySide6 / Qt 6 (sinais, layout base, pixmaps e ciclo de vida)
│   ├── pages/                  # Pacote declarativo das 4 páginas Qt 6 (UIPagesMixin)
│   │   ├── __init__.py         # Combina os 4 mixins de página + helpers (_create_scroll_page, _create_reload_button)
│   │   ├── video_page.py       # Página 0: Video Settings (PS4 Camera, Webcam, Phone Camera QR e Display Options)
│   │   ├── tracking_page.py    # Página 1: Quality Presets (Performance/Balanced/High/Custom), 1P/2P e 4 opções manuais de Tracking
│   │   ├── experimental_page.py# Página 2: Experimental Features (Auto-Frame PTZ nos modos de câmera)
│   │   └── ds4_page.py         # Página 3: DualShock 4 Controller Settings (com cartão PlayStation Move Emulator ZCM2)
│   ├── styles.py               # Construtor centralizado da folha de estilos QSS (PlayStation Blue / Crisp White)
│   ├── mixins/                 # Mixins modulares de apresentação e handlers de eventos da janela Qt 6
│   │   ├── __init__.py         # Exports unificados dos 5 mixins da interface
│   │   ├── device_readout.py   # UIDeviceReadoutMixin (readouts ao vivo de DS4, PS Move Emulator e Phone Camera)
│   │   ├── camera_handlers.py  # UICameraHandlersMixin (modos, abas, PS4 Camera state, Webcam e presets)
│   │   ├── phone_handlers.py   # UIPhoneHandlersMixin (Phone Camera QR, IP LAN, Firewall e desconexão)
│   │   ├── ds4_handlers.py     # UIDS4HandlersMixin (DualShock 4, sincronia Light Bar/Rumble PS Move e Logs)
│   │   └── tracking_handlers.py   # UITrackingHandlersMixin (calibração, 2P, download de modelos AI e Start/Stop)
│   ├── widgets.py              # Componentes Qt 6 reutilizáveis (SlidingStackedWidget, DeviceNavCard, CalibPresetCard, SettingBlock)
│   ├── theme.py                # Paleta de cores, tipografia e Quality Presets (Performance, Balanced [RECOMMENDED], High, Custom)
│   ├── icons.py                # Gerador e renderizador de ícones vetoriais e supersampled
│   └── controllers/            # Camada de Controle Desacoplada (MVP / Controller Facade)
│       ├── __init__.py         # Exports unificados da camada de controle
│       ├── app_controller.py   # SensorAppController (fachada central QObject que coordena a aplicação)
│       ├── camera_controller.py# CameraController (descoberta PnP, warm-up assíncrono, standby throttling)
│       ├── device_controller.py# DeviceController (Phone Camera HTTPS/WSS, DS4 HID/Bluetooth e readout PS Move ZCM2)
│       └── session_controller.py# SessionController (orquestrador do loop de rastreamento, Kinect/PS Move daemon e IPC)
├── assets/                     # Recursos visuais e mídias
│   ├── icons/                  # Ícones SVG/PNG, app_icon.ico e splash.png ("Hold on... and warm up!")
│   ├── fonts/                  # Fontes TTF (Kanit, InterTight, NationalPark)
│   └── webapp/                 # Templates HTML5/CSS/JS estáticos do Phone Camera WebApp (mobile_webapp.html, expired_session.html)
├── models/
│   ├── pose_landmarker_lite.task  # Modelo MediaPipe Pose Lite (Perfil Competitivo — embutido offline)
│   └── pose_landmarker_full.task  # Modelo MediaPipe Pose Full (Perfil Equilibrado — cache sob demanda em %APPDATA%\models)
└── tools/
    ├── Legacy10.dll               # DLL proxy Kinect de 32 bits injetada em memória (Legacy.exe)
    ├── Legacy10_x64.dll           # DLL proxy Kinect de 64 bits injetada em memória (Legacy Lab.exe / LegacyLab_Offline.exe)
    ├── legacy10_x64_src/          # Código-fonte C++ e arquivo .def da Legacy10_x64.dll (ABI Kinect SDK v1.8 x64)
    ├── LegacyMove.dll             # DLL proxy PlayStation Move ZCM2 de 32 bits injetada em memória (Legacy.exe)
    ├── LegacyMove_x64.dll         # DLL proxy PlayStation Move ZCM2 de 64 bits injetada em memória (Legacy Lab / Offline)
    ├── legacymove_src/            # Código-fonte C++ da LegacyMove.dll / LegacyMove_x64.dll (SetupAPI/HID/Kernel32 IAT)
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
- **Responsabilidade:** Inicialização da aplicação, parsing de parâmetros da linha de comando (`--version`, `--portable`, `--start`, `--mode`, `--camera`) e carregamento da GUI (com aplicação de `cli_overrides`) ou da sessão de rastreamento direto.
- **Relações:** Instancia `ConfigManager` e aciona `ui.launch_app(cli_overrides=...)` ou `tracking_session.py`.

### 2. `gui_qt.py`, `ui/mixins/` e `ui/pages/` — Interface do Usuário (Painel de Controle PlayStation em Qt 6)
- **Responsabilidade:** Interface visual moderna desenvolvida em **PySide6 (Qt 6)**, dividida entre a casca principal da janela (`gui_qt.py`), os 5 mixins de eventos e readouts (`ui/mixins/`), o pacote declarativo das 4 páginas de navegação (`ui/pages/`: `video_page.py`, `tracking_page.py`, `experimental_page.py`, `ds4_page.py` expostos via `UIPagesMixin`) e os componentes reutilizáveis (`widgets.py`, incluindo `SettingBlock`). Conta com animações fluidas de transição entre abas (`SlidingStackedWidget`), layout dividido com barra lateral estilizada de seleção de dispositivo (PlayStation 4 Camera, Webcam Padrão, DualShock 4 e Phone Camera), abas superiores centralizadas ("Video Settings", "Tracking", "Controller Settings", "Experimental"), paleta oficial PlayStation Blue (`#00439C`), cards com sombras suaves e ícones vetoriais anti-aliased. Permite selecionar entre os 4 Quality Presets de rastreamento (**Performance**, **Balanced — Lite AI recomendado**, **High — Full AI** e **Custom** ativado automaticamente ao alterar qualquer controle manual de `AI Model`, `Inference Quality`, `Silhouette Cutout` ou `Player Lock`), conta com calibração automática, cartão **PLAYSTATION MOVE EMULATOR (NATIVE ZCM2)** integrado dentro de `ds4_info_frame` (exibido somente quando um DualShock 4 está conectado, com amostra RGB da esfera ao vivo e toggle de sincronia da Light Bar/Rumble) e aba Experimental contextual por modo.
- **Ciclo de Vida do Driver e Hotplug Reativo:** Monitora a cada 1.0 segundo o hardware PnP e o ciclo de vida da PS4 Camera (`NOT_INSTALLED`, `DISCONNECTED`, `DRIVER_STOPPED`, `BOOTLOADER_UPLOADING`, `WAITING_VCAM`, `READY`).
- **Threading Não-Bloqueante:** Tanto a enumeração de câmeras do OpenCV quanto o desligamento de câmeras pré-aquecidas em standby (`CameraController.cancel_warmup(sync=False)` com thread `CameraPrewarmCloser` serializada) e a sessão de rastreamento executam em threads assíncronas dedicadas, mantendo a janela do Qt 6 totalmente fluida a 60 FPS e sem congelamentos ao trocar de modo (ex.: `Webcam → DualShock 4` ou `Phone Camera`).

### 3. `camera_manager.py`, `camera_win32.py`, `framebus_reader.py` e `camera_capture.py` — Subsistema de Câmera e Captura Assíncrona
- **Classe `LatestFrameCamera` (`camera_capture.py`, re-exportada por `camera_manager.py`):** Executa um loop contínuo de captura de quadros em thread separada com um buffer atômico de profundidade 1 e contador monotônico de sequência (`frame_seq`). Com `read(only_new=True)`, o loop de rastreamento consome apenas quadros de hardware inéditos, eliminando 100% do reprocessamento de frames duplicados quando o loop roda mais rápido que a câmera.
- **Leitura Direta do FrameBus com Bypass DirectShow (`FrameBusReader` em `framebus_reader.py`):** Conecta-se diretamente à memória compartilhada `Global\PSCam4Win{slot}.FrameBus` para ler frames `YUY2` sem cópias intermediárias. Quando o `FrameBus` já está ativo e transmitindo, o `LatestFrameCamera._open_and_negotiate()` ignora a negociação de 1 a 2 segundos da câmera virtual DirectShow (`cv2.VideoCapture`) e inicia a captura imediatamente, mantendo o DirectShow apenas como fallback preguiçoso (*lazy fallback*).
- **Snapshot Rápido de Hardware PnP (`get_hardware_snapshot` em `camera_win32.py`):** Utiliza diretamente a DLL nativa `cfgmgr32.dll` (`CM_Get_Device_ID_ListW`) com filtro de dispositivos presentes, retornando uma assinatura de hardware em menos de **3 milissegundos**, sem a sobrecarga de subprocessos como `pnputil`.
- **Máquina de Estados da PS4 Camera (`get_ps4_camera_state`):** Rastreia os IDs de hardware USB (`VID_05A9&PID_0580` do bootloader e `VID_05A9&PID_058B` do sensor ativo) e a contagem de câmeras virtuais (`SWD\VCAMDEVAPI`) para determinar o status exato da câmera.
- **Negociação de Formatos (FourCC):** Identifica a PlayStation 4 Camera (`is_pscam=True`) e preserva o stream nativo em **YUY2 / NV12**, evitando a definição forçada de `'MJPG'` que corrompe a negociação com a câmera virtual do driver.
- **Enumeração de Dispositivos:** Cruza os índices do OpenCV com a lista de dispositivos PnP do Windows via SetupAPI (`camera_win32.py`, ~3ms) com fallback WinRT/PowerShell para exibir nomes amigáveis na interface.

### 4. `pose_tracker.py`, `body_mask.py` e `pose_filters.py` — Motor de Pose, Máscara Anatômica e Cinemática
- **`PoseTracker`:** Inicializa e gerencia a rede neural `vision.PoseLandmarker` do Google MediaPipe no modo contínuo de vídeo (`RunningMode.VIDEO`), preservando as proporções nativas de aspecto da câmera e operando com limiares otimizados (`det_c <= 0.45`, `pres_c <= 0.35`) para garantir detecção contínua e sem perda de rastreamento.
- **Pré-Downscaling In-Place & Adaptive Inference Width (`640 → 384 → 320px`):** Para streams HD como `1280x800` (PS4 Camera) ou `1920x1080` (Webcams Full HD), redimensiona in-place em buffers pré-alocados (`_infer_bgr` e `_infer_rgb`) antes de enviar ao MediaPipe, mantendo os quadros originais em resolução total para a triangulação estéreo sub-pixel (`StereoDepthEngine`). Em modo 1P sob alta carga de CPU (`infer_ms_ema > 48 ms`), o escalonamento adaptativo reduz automaticamente o buffer de entrada (`640 → 384 → 320px`, casando 1:1 com a máscara nativa `320x240` do Kinect) e restaura com histerese quando a CPU alivia.
- **Garantia de Monotonicidade:** Força que `timestamp_ms` seja estritamente incremental a cada frame (`timestamp_ms = max(now_ms, last_ms + 1)`), prevenindo quebras em 60 FPS estáveis.
- **Sintetizador Independente de Membros Inferiores (Por Perna & Segmento):** Quando o jogador está diante de uma mesa ou executa chutes/giros com oclusão temporária de um único tornozelo, cada perna é avaliada de forma independente (mantendo a perna visível e joelhos visíveis intactos e sintetizando apenas o segmento oculto com confiança `0.35` / `INFERRED`, e quadris com confiança >= 0.48 / `TRACKED`).
- **`HandAnchorFilter` + Centro de Palma (`INDEX + PINKY`):** Sintetiza `HandLeft`/`HandRight` no ponto médio ponderado por confiança entre `INDEX` e `PINKY` (alinhado ao centro da palma do Kinect v1) e aplica proteção anatômica contra distensão (>16 cm), colapso (<4 cm) ou dobramento invertido do punho, extrapolando ao longo do vetor `cotovelo -> pulso` quando a confiança dos dedos cai.
- **`AdaptiveSmoother` Independente de FPS com Desacoplamento XY/Z (`dt`-Compensated Continuous EMA 3D & 2D):** Filtro EMA compensado continuamente por `dt` (`eff_alpha = 1 - (1 - alpha_ref) ** (dt / REF_DT)`) com *deadzone* de velocidade (`VEL_DEADZONE = 0.010m`), suavização independente para XY e Z (piso de repouso mais firme em Z para suprimir ruído monocular sem atrasar golpes frontais), extremidades estáveis em poses paradas (sem amplificação de tremedeira em repouso, escalando até `0.96` em golpes rápidos) e proteção escalonada por `dt` contra saltos espúrios de 1 frame (>35 cm).
- **`SkeletonCalibrator` Multi-Tier com Refinamento Progressivo & Estéreo Coerente de Tronco:** Opera em 3 níveis adaptativos (`full_body`, `flexible_torso`, `upper_body`) com refinamento progressivo suave da escala nos primeiros ~30 frames eretos em corpo inteiro. Quando a Visão Estéreo da PS4 Camera está ativa, triangula exclusivamente os **8 joints de tronco** (`0, 1, 2, 3, 4, 8, 12, 16`, ~4× menor custo de CPU) para ancorar a distância métrica de sala (`stereo_baseline_z`), preservando a profundidade relativa dos membros 100% coerente com o esqueleto 3D do MediaPipe (eliminando *Z-popping* frame a frame em punhos/mãos/cotovelos).
- **Ancoragem Métrica de Altura do Quadril & Rastreamento Vertical de Agachamento/Salto (`CameraSpaceYTracker`):** Mantém a convenção nativa do Kinect v1 (`hip_height_m: 1.0`) enquanto rastreia dinamicamente deslocamentos verticais de agachamentos, *bounces* e saltos (`[-0.42m, +0.30m]`) relativos a uma linha de base ereta de adaptação lenta normalizada pelo tronco, preservando `dy = 0` em enquadramentos de mesa.
- **Rastreador de Espaço de Câmera (`CameraSpaceXTracker` & `apply_slot_snap` Contínuo):** Mapeia o deslocamento horizontal do jogador na sala (com suavização compensada por `dt`) para a faixa lateral do palco de $\pm 1.4\text{m}$ e aplica `apply_slot_snap` com curva linear por partes $C^0$-contínua na zona morta (eliminando saltos discretos ao cruzar $\pm 6\text{cm}$).
- **Ordem Ótima do Pipeline:** O esqueleto anatômico é suavizado pelo `AdaptiveSmoother` *antes* da translação lateral de sala e do encaixe de slots. Isso assegura que o filtro EMA não restrinja nem atrase a seleção dinâmica de dançarinos.
- **`build_body_mask` Nativo em `320x240`:** Gera e aplica o fechamento morfológico da máscara de segmentação anatômica diretamente na resolução nativa do Kinect (`320x240`), reduzindo em 13x o custo de CPU em câmeras `1280x800` e fundindo via bitwise-OR com a segmentação neural do MediaPipe.

### 5. `tracking_session.py` — Orquestrador do Loop de Rastreamento
- **Responsabilidade:** Conecta todos os módulos durante o jogo:
  1. Abre a câmera via `LatestFrameCamera`.
  2. Inicializa o `PoseTracker` e o `KinectBridge`.
  3. No loop principal, aguarda apenas frames novos da câmera (`camera.read(only_new=True)`), processa o frame bruto na IA, grava os 20 joints e a máscara de imagem no `KinectBridge`, gera o frame espelhado com overlay visual (silhueta, contorno e esqueleto) e bombeia eventos de teclado (`cv2.waitKey(1)`).
  4. Trata atalhos: `[C]` Recalibrar, `[O]` Rotacionar câmera, `[H]` Ciclar HUD, `[P]` Alternar modo Picture-in-Picture (Always-On-Top), `[Q/ESC]` Sair.
  5. Fecha e desaloca os recursos de forma limpa ao encerrar.

### 6. `tracking_overlay.py` — Renderizador de HUD, Silhueta, Esqueleto e Efeitos Gamificados
- **Responsabilidade:** 
  1. `draw_rounded_glass_pill`: Desenho ultra-otimizado (< 0.05ms) de cápsulas flutuantes translúcidas ("Glass Pills") com cantos arredondados e bordas anti-aliasing sobre ROIs restritos.
  2. `draw_player_silhouette`: Extrai os contornos da máscara anatômica `320x240`, escala os vértices para o frame de preview e renderiza a silhueta semitransparente ("sombrinha") com contorno neon duplo (glow suave colorido de 3px + linha branca nítida de 1px com `cv2.LINE_AA`).
  3. `draw_skeleton`: Desenha articulações e ossos coloridos por jogador (P1 Azul / P2 Laranja Claro).
  4. `draw_gesture_feedback`: Anel radial neon de progresso (0° a 360°) posicionado dinamicamente ao redor da mão erguida do jogador (`hand_pos`), com ponto luminoso orbitante e ondas expansivas verdes ao disparar o comando de `[ENTER]`.
  5. `draw_hud` e `draw_controller_hud`: Interface moderna dividida em cápsulas flutuantes (modo câmera: Branding, FPS & IPC, Status dos Dançarinos e Atalhos; modo DualShock 4: Branding, Telemetria Hz/Bateria/PS Move, Orbe RGB da esfera sincronizada, Motion Force 3D e mapa de botões PS Move). Suporta 3 modos cicláveis com a tecla `[H]` (Modo 0: Completo, Modo 1: Minimalista, Modo 2: Desligado/Espelho Puro).

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
  1. Suporta nativamente relatórios padrão `0x01` (64 bytes) e relatórios estendidos `0x11` (78 bytes), incluindo leitura analógica do gatilho `R2` (`0..255`).
  2. Suporte adaptativo de Output Report para vibração háptica (rumble) e lightbar RGB (`32 bytes` report `0x05` ou `78 bytes` report `0x11` com CRC-32).
  3. Calibração automática de zero-bias do giroscópio em repouso (primeiras 50 amostras estáveis) e streaming em tempo real dos 6 eixos IMU + botões 1:1 para o `PSMoveSharedMemory`.
  4. Polling de feedback a ~30 Hz lendo a cor RGB da esfera do PS Move e o rumble enviados pelo Just Dance (`0x06`/`0x02`) e espelhando-os na Light Bar e motores hápticos do DualShock 4 (restaurando PlayStation Blue `(0, 67, 156)` ao encerrar).
  5. Desacoplamento total de hardware de câmera durante o modo de controle.
  6. Modo Permissivo com identificação amigável do modelo (`detect_controller_name`), bloqueio preventivo de gamepads Xbox e diagnóstico contínuo de sensor IMU congelado (`imu_frozen`).

### 10. `psmove_shared_memory.py` & `tools/LegacyMove*.dll` — Emulador Nativo de PlayStation Move (ZCM2)
- **Responsabilidade:** Emula um controle **PlayStation Move Motion Controller ZCM2** (`VID 0x054C / PID 0x0C5E`) diretamente na memória RAM do Just Dance PC (`Legacy.exe` x86, `Legacy Lab.exe` x64 e `LegacyLab_Offline.exe` x64), sem depender de servidor WebSocket ou drivers de kernel:
  1. **Memória Compartilhada Seqlock (`Local\LegacyPSMoveState`, 128 bytes, `PSM1`):** Bloco bidirecional com 64 bytes Sensor→Jogo (acelerômetro 3D, giroscópio 3D, máscara de botões PS Move, gatilho `T`, nível de bateria e flag `active`) e 64 bytes Jogo→Sensor (RGB da esfera e rumble).
  2. **Alinhamento Ergonômico da Pegada Vertical ("Joinha"):** Aplica rotação própria 3D ($\det = +1$) mapeando `(move_x, move_y, move_z) = (+ds4_x, -ds4_z, +ds4_y)` para que a barra de luz do DualShock 4 apontando para cima coincida com a esfera do PS Move (`+Y_move = +4400` counts em repouso) e o touchpad frontal coincida com os botões frontais do PS Move (`+Z_move`).
  3. **Proxy IAT In-Process (`LegacyMove.dll` / `LegacyMove_x64.dll`):** Intercepta funções `SETUPAPI.dll`, `HID.DLL` e `KERNEL32.dll` dentro do processo do jogo com 100% de passthrough para dispositivos HID reais. Quando `active == 0` (modos de câmera), o PS Move virtual fica 100% invisível ao jogo. Quando `active == 1`, sintetiza relatórios ZCM2 de 49 bytes (`0x01`) a 100 Hz via `ReadFile` overlapped e grava os comandos `0x06`/`0x02` de `WriteFile` no canal de feedback.

### 11. `telemetry_benchmark.py` — Utilitários de Análise de Telemetria CSV
- **Responsabilidade:** Módulo utilitário de backend para análise de séries temporais de aceleração gravadas em `logs/`:
  1. Parsing de arquivos CSV de telemetria nos formatos legado (10 colunas) e estendido (13 colunas).
  2. Alinhamento temporal via correlação cruzada (*cross-correlation*) e reamostragem a 60 Hz.
  3. Cálculo de métricas comparativas: correlação de Pearson, atraso/latência média em milissegundos, picos G e P95.

### 12. `session_logger.py` — Subsistema de Log de Sessão e Telemetria de Dança (Diagnóstico de Suporte)
- **Responsabilidade:** Coordena o ciclo de vida de diagnóstico e o streaming de telemetria contínua da dança em tempo real.
  1. **Ciclo de Vida na Inicialização (Startup Reset):** Limpa e reinicia o log ao abrir o aplicativo, preservando automaticamente o log anterior em `logs/session_previous.log` para segurança contra reaberturas acidentais.
  2. **Cabeçalho Diagnóstico Completo de Sistema:** Registra metadados do Windows (Build/Versão), modelo de CPU, contagem de núcleos, memória RAM física total e disponível via API Win32 `GlobalMemoryStatusEx`, runtime Python (PE compilado vs script) e versão do aplicativo.
  3. **Mapeamento Ativo de Controles:** Detecta e registra o dispositivo de controle em uso (DualShock 4 Bluetooth/USB em modo PS Move ZCM2 ou Câmera Óptica), atualizações de bateria e modo de conexão.
  4. **Streaming de Telemetria de Dança (CSV Assíncrono):** A partir do momento do `START TRACKING`, grava em buffer assíncrono em lote (batching) todas as métricas de movimento ($a_x, a_y, a_z, |G|$, velocidade da mão, coordenadas dos joints e FPS) com impacto computacional nulo (<0,1% CPU).
  5. **Resiliência a Falhas (Crash Diagnostics):** Instala interceptores globais para `sys.excepthook` e `threading.excepthook`, garantindo que qualquer encerramento inesperado grave o stack trace completo e feche os arquivos de forma limpa.

### 13. `kinect_emulator.py` — Emulador Zero-File Seletivo em Memória (Kinect OU PlayStation Move — 32-bit Legacy & 64-bit Legacy Lab)
- **Responsabilidade:** Detecção instantânea do processo do Just Dance Legacy (32-bit `Legacy.exe`) e **Legacy Lab / Legacy Lab Offline (64-bit `Legacy Lab.exe`, `LegacyLab_Offline.exe`)** com injeção seletiva por modo diretamente na memória RAM, sem injeção dupla desnecessária e sem modificar arquivos no disco:
  1. **Detecção Leve via Toolhelp32:** Varredura em tempo real (< 0.5 ms) identificando processos 32-bit (`Legacy.exe`, `JustDance.exe`) e 64-bit (`Legacy Lab.exe`, `LegacyLab_Offline.exe`), rejeitando launchers (`legacylab-launcher.exe`).
  2. **Injeção Seletiva por Modo (Zero Injeção Dupla):**
     - **Modos de Câmera (`pscam`, `webcam`, `phone_cam`):** Injeta exclusivamente `tools/Legacy10.dll` (32 bits) ou `tools/Legacy10_x64.dll` (64 bits) e aplica patch atômico na IAT / Delay-IAT do Kinect (canais `JDP2`/`JMI2`/`JDP1`/`JMI1`/`JXC1`).
     - **Modo DualShock 4 (`ds4`):** Injeta exclusivamente `tools/LegacyMove.dll` (32 bits) ou `tools/LegacyMove_x64.dll` (64 bits) para emulação nativa de PlayStation Move ZCM2 (`Local\LegacyPSMoveState`), mantendo o Kinect totalmente fora do processo para evitar conflito de sensores.
     - Se o usuário trocar de modo com o jogo já aberto, o daemon anexa a DLL correspondente sob demanda.
  3. **Hardening & Diagnóstico:** Staging seguro em `%APPDATA%\LegacyPSCam_Sensor\tools\`, `PAGE_READWRITE`, diagnóstico explícito de `ERROR_ACCESS_DENIED (5)` e exposição de `kinect_hooked` e `psmove_hooked` em `get_status()`.

### 14. `player_slot.py` e `player_reid.py` — Pipeline Multi-Jogador (1P/2P) & Memória Re-ID Anti-Swap
- **Responsabilidade:** Separação modular entre o estado cinemático/máscara por slot (`player_slot.py`: `PlayerSlotState`, `PlayerFrame`, `MultiPoseFrame`, `compose_player_index_mask`) e o motor de re-identificação/plausibilidade (`player_reid.py`: `AppearanceSignature`, `LongTermIdentityProfile`, `MultiPlayerAssociator`, `is_plausible_human_dancer`, `suppress_duplicate_poses`):
  1. **Isolamento de Slots:** Cada dançarino opera seu próprio pipeline desacoplado com `HandAnchorFilter`, `AdaptiveSmoother`, `SkeletonCalibrator`, `CameraSpaceXTracker` e `PersonLockController`.
  2. **Detecção Dinâmica (`num_poses=3` em 2P) com Filtro Anatômico Unificado (`is_plausible_human_dancer`) e Pose NMS (`suppress_duplicate_poses`):** Em modo 2P, o MediaPipe opera com `num_poses=3`. Todos os candidatos passam pela validação anatômica unificada e por supressão de duplicatas baseada em geometria de tronco antes da atribuição de slots, eliminando falsos-positivos e propostas duplicadas.
  3. **Resolução de Inferência Otimizada (640px):** Buffer de inferência pré-redimensionado em 640px de largura, garantindo alta densidade de amostragem e estabilidade nas articulações periféricas (punhos e pés) para ambos os dançarinos.
  4. **Inércia Espacial de Slot & Trava de Aglomeração:** Aplica bônus de continuidade espacial (`CURRENT_SLOT_INERTIA_BONUS = 0.22`) e congela atualizações de assinatura visual durante sobreposições (`is_crowded`), impedindo contaminação de cor ou trocas impulsivas durante valsas e cruzamentos.
  5. **Momentum Cinemático Direcional:** Recompensa o vetor de deslocamento $(\vec{v} \cdot \vec{d})$ alinhado com a velocidade física dos dançarinos durante cruzamentos.
  6. **Auditoria de Separação:** Compara as assinaturas visuais multi-região contra as âncoras permanentes (`anchor_sig`) após o término do contato corporal, corrigindo qualquer inversão involuntária.

### 15. `camera_manager.py` — Pipeline de Câmera com Warm-Up em Standby & Lazy Loading PEP 562
- **Responsabilidade:** Pré-negociação do sensor de vídeo em segundo plano e transferência atômica com latência zero para o loop de rastreamento:
  1. **Background Camera Pre-Warming:** Instancia `LatestFrameCamera` 400ms após a renderização da interface gráfica em modo standby (`is_prewarming=True`), negociando DirectShow e WinUSB antecipadamente sem travar a interface.
  2. **Standby Throttling (<0.4% CPU):** Reduz a taxa de polling em idle para ~12 FPS no menu, eliminando consumo desnecessário de CPU antes do início da dança.
  3. **Handoff Atômico e Ativação Instantânea (`activate_live()`):** Ao clicar em "START TRACKING", a instância pré-aquecida é adotada instantaneamente pelo `tracking_session.py` com latência de ~0.3s (redução de 84% frente aos ~2.3s de negociação DirectShow fria).
  4. **Verificação de Compatibilidade (`is_compatible()`):** Se o usuário alterar resolução, preset, orientação ou olho da PS4 Camera, a instância anterior é reciclada com debounce de 300ms.
  5. **Lazy Loading PEP 562:** Submódulos secundários (`phone_camera`, `psmove_shared_memory`, `ds4_controller`, `telemetry_benchmark`) são carregados sob demanda apenas quando ativados pelo usuário, acelerando a inicialização da aplicação.

### 16. `ui/controllers/` — Camada de Controle Desacoplada (MVP / Controller Facade)
- **Responsabilidade:** Isola completamente a camada visual (`gui_qt.py`) da lógica de baixo nível, hardware, sockets e threads IPC:
  1. **`app_controller.py` (`SensorAppController`):** Fachada central (`QObject`) que atua como ponto único de coordenação entre os subcontroladores e a interface gráfica. Expõe sinais Qt thread-safe (`cameras_refreshed`, `pscam_state_changed`, `tracking_finished`), validação unificada pré-rastreamento (`validate_pre_tracking`) e limpeza determinística (`cleanup`).
  2. **`camera_controller.py` (`CameraController`):** Gerencia a descoberta de hardware PnP em tempo real, monitoramento da máquina de estados da PS4 Camera, thread pool de warm-up em standby com throttling adaptativo, compatibilidade de presets e transição atômica de câmera.
  3. **`device_controller.py` (`DeviceController`):** Orquestra o ciclo de vida do servidor Phone Camera (HTTPS/WSS e geração PIL de QR Code), DualShock 4 (descoberta HID/Bluetooth, rumble, verificação de IMU congelada, leitura contínua de acelerômetro e preferência de sincronia da Light Bar) e readout em tempo real da emulação PlayStation Move (`get_psmove_readout`). Opera inteiramente sob demanda via PEP 562.
  4. **`session_controller.py` (`SessionController`):** Gerencia a thread de execução do rastreamento corporal/controle em background (`tracking_session.py`), a instância do emulador em memória (`KinectEmulatorDaemon`) e o fechamento seguro dos canais de memória compartilhada Windows (`KinectBridge` e `close_psmove_bridge`).

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
