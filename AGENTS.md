# Diretrizes do Projeto — Legacy Sensor Lite (Kinect Simulator para Just Dance PC)

Este documento define o contexto, a arquitetura, as convenções e as regras operacionais que todos os agentes de IA devem seguir rigorosamente ao manter ou implementar funcionalidades neste repositório.

---

## 🎯 Missão e Escopo do Projeto

O objetivo do **Legacy Sensor Lite** é fornecer um sensor de movimento corporal de alto desempenho, ultraleve e direto ao ponto para o jogo **Just Dance PC (Legacy Offline)**, unificando o suporte a **Webcams USB/Integradas** e à **PlayStation Camera (PS4 Camera / OV580)**.

### Princípios Fundamentais (Invioláveis)
1. **Zero Bloatware:** Sob nenhuma circunstância reintroduza componentes irrelevantes do emulador original (como arquivos de áudio/música de fundo MP3, sistemas de moedas/XP/níveis, animações de presentes, vídeos de abertura ou telemetria). O aplicativo deve permanecer enxuto, rápido e focado exclusivamente na dança.
2. **Latência Mínima e 60 FPS:** O pipeline de vídeo e rastreamento deve suportar taxas de até 60 FPS estáveis para a PlayStation Camera e webcams de alta velocidade sem sobrecarregar a CPU.
3. **Preservação do Contrato Binário da Memória Compartilhada:** O Just Dance PC consome dados através do `Kinect10.dll` via dois canais de memória compartilhada Windows com seqlock:
   - `Local\LegacyWebcamKinectPose`: 344 bytes fixos contendo cabeçalho e as 20 articulações corporais.
   - `Local\LegacyWebcamKinectImage`: 1.305.632 bytes contendo cabeçalho de 32 bytes, frame de câmera 640x480 BGRA e máscara de segmentação do jogador 320x240 (player index mask) para a silhueta no HUD do jogo.
4. **Isolamento de Responsabilidades:** O processamento matemático de visão computacional, o gerenciamento de câmera, a comunicação IPC e a interface gráfica devem permanecer desacoplados.
5. **Identidade Visual Limpa (Sem Menções a "Simulador Kinect"):** Toda a interface do usuário, títulos de janelas, cabeçalhos e documentação externa devem apresentar o aplicativo como **Legacy Sensor Lite** (Sensor de Movimento para Just Dance PC), evitando termos legados como "simulador kinect" na UI.

---

## 🏛️ Arquitetura do Sistema

O projeto é organizado nos seguintes módulos na pasta `LegacyPSCam_Sensor/`:

```
LegacyPSCam_Sensor/
├── main.py                     # Ponto de entrada (CLI dispatcher e inicializador)
├── test_suite.py               # Suíte de testes automatizados (9/9 suítes integradas)
├── config.json                 # Gerenciamento e persistência das configurações locais
├── sensor/                     # Pacote do Motor de Rastreamento e Visão Computacional
│   ├── __init__.py             # Exports unificados da API do sensor
│   ├── camera_manager.py       # Descoberta, negociação DirectShow/MSMF e captura assíncrona
│   ├── pose_tracker.py         # Motor MediaPipe Pose, Hand Anchor, Calibrador, EMA e Máscara Corporal
│   ├── kinect_shared_memory.py # Driver IPC com KinectBridge (JDP1 344 bytes + JMI1/2 1.3MB + JXC1 28 bytes)
│   ├── tracking_session.py     # Orquestrador do loop de rastreamento e eventos de teclado
│   ├── tracking_overlay.py     # Renderização visual do esqueleto, silhueta sombreada e HUD em OpenCV
│   └── config_manager.py       # Gerenciamento e persistência das configurações (config.json)
├── ui/                         # Pacote da Interface Gráfica
│   ├── __init__.py             # Exporta a classe LegacySensorGUI
│   └── gui.py                  # Interface gráfica moderna dark em Tkinter / ttk
├── assets/                     # Recursos visuais e mídias
│   ├── IconePSCAMERA.png       # Ícone da PlayStation 4 Camera
│   └── models/                 # Modelos neurais locais
├── models/
│   └── pose_landmarker_lite.task # Modelo pré-treinado do Google MediaPipe Pose
├── tools/
│   ├── PSCam4Win-Setup.exe       # Instalador oficial do driver da PlayStation Camera
│   └── get_cameras.ps1           # Script PowerShell auxiliar para enumeração de câmeras WinRT
└── Kinect for Legacy DLL/
    └── Kinect10.dll              # DLL proxy de 32 bits para a pasta do Just Dance PC
```

### Fluxo de Dados em Execução
```
[ Câmera: Webcam ou PS Camera ]
            │ (Frames BGR via LatestFrameCamera)
            ▼
   [ pose_tracker.py ]
   ├── MediaPipe PoseLandmarker (33 landmarks)
   ├── HandAnchorFilter (extrapolação do antebraço para mãos velozes)
   ├── AdaptiveSmoother (filtro dinâmico EMA anti-jitter)
   ├── SkeletonCalibrator (normalização de escala e inversão do eixo X)
   └── build_body_mask (máscara anatômica do tronco, membros e cabeça)
            │ (20 articulações Kinect + Máscara de Segmentação)
            ├─────────────────────────────────────────┐
            ▼                                         ▼
[ kinect_shared_memory.py (KinectBridge) ]    [ tracking_overlay.py ]
  Grava em:                                    Renderiza:
  - Local\LegacyWebcamKinectPose (JDP1 344B)   - Silhueta semitransparente ("sombrinha")
  - Local\LegacyWebcamKinectImage (JMI1 1.3MB) - Contorno neon anatômico
  - Local\LegacyWebcamKinectCoachX (JXC1 28B)  - Esqueleto Kinect colorido
            │                                  - HUD espelhado e métricas FPS
            ▼                                         │
   [ Kinect10.dll ]                                   ▼
  Lido pelo Just Dance PC                       [ cv2.imshow ]
  - NuiSkeletonGetNextFrame (Pose)             Janela de feedback visual
  - NuiImageStreamGetNextFrame (Silhueta HUD)
```

---

## 📐 Contrato Binário da Memória Compartilhada (Kinect Bridge)

O sistema IPC opera com canais mapeados em memória Windows sob o protocolo seqlock:

### 1. Canal de Pose (`Local\LegacyWebcamKinectPose` — 344 bytes)
- **Cabeçalho (24 bytes):** `<IIIIQ`
  1. `magic` (uint32): `0x3150444A` (`JDP1`)
  2. `version` (uint32): `1`
  3. `seq` (uint32): Número de sequência seqlock (ímpar durante gravação, par quando consistente)
  4. `tracked` (uint32): `1` se o corpo estiver sendo rastreado, `0` se perdido
  5. `timestamp_ms` (uint64): Timestamp Unix em milissegundos
- **Articulações (320 bytes):** 20 joints no formato `<ffff` (X, Y, Z, Confiança)
  - Ordem obrigatória das 20 articulações do Kinect v1:
    `0: HipCenter`, `1: Spine`, `2: ShoulderCenter`, `3: Head`,
    `4: ShoulderLeft`, `5: ElbowLeft`, `6: WristLeft`, `7: HandLeft`,
    `8: ShoulderRight`, `9: ElbowRight`, `10: WristRight`, `11: HandRight`,
    `12: HipLeft`, `13: KneeLeft`, `14: AnkleLeft`, `15: FootLeft`,
    `16: HipRight`, `17: KneeRight`, `18: AnkleRight`, `19: FootRight`.

### 2. Canal de Imagem e Silhueta (`Local\LegacyWebcamKinectImage` — 1.305.632 bytes)
- **Cabeçalho (32 bytes):** `<IIIIIIQ`
  1. `magic` (uint32): `0x31494D4A` (`JMI1`)
  2. `version` (uint32): `1`
  3. `seq` (uint32): Número de sequência seqlock
  4. `tracked` (uint32): `1` se jogador ativo, `0` se ausente
  5. `width` (uint32): `640`
  6. `height` (uint32): `480`
  7. `timestamp_ms` (uint64): Timestamp Unix em milissegundos
- **Frame de Câmera (1.228.800 bytes):** 640x480 pixels no formato BGRA (4 canais).
- **Máscara de Jogador (76.800 bytes):** 320x240 pixels (player index mask de profundidade: `1` = Jogador 1, `0` = Fundo). Crucial para o Just Dance exibir a silhueta no HUD inferior e na seleção de dançarinos.

---

## ⚠️ Regras Críticas de Desenvolvimento para Agentes

1. **Nunca espelhe o frame antes da inferência do MediaPipe:**
   - O MediaPipe deve SEMPRE inferir sobre o frame bruto original capturado da câmera.
   - O espelhamento (`cv2.flip(frame, 1)`) deve ser aplicado **apenas** no frame exibido na janela do usuário e nas coordenadas de renderização do HUD 2D.
   - Espelhar o frame antes da inferência inverte anatomicamente o braço esquerdo e direito, fazendo com que o Just Dance registre 0 pontos em todas as músicas.
2. **Garantia de Timestamps Estritamente Monotônicos:**
   - O MediaPipe Pose Tasks API em modo `RunningMode.VIDEO` lança `ValueError` se receber dois frames com o mesmo timestamp em milissegundos.
   - Ao processar frames em alta taxa (60 FPS ou mais), garanta sempre `timestamp_ms = max(now_ms, last_timestamp_ms + 1)`.
3. **Preservação de FourCC para PlayStation Camera:**
   - O driver PSCam4Win entrega vídeo nativo em **YUY2** ou **NV12**. Nunca force o FourCC para `'MJPG'` em câmeras PS Camera, pois isso corrompe a negociação DirectShow do driver.
4. **Tratamento de I/O de Câmera Assíncrono:**
   - A leitura da câmera deve permanecer na classe `LatestFrameCamera` em thread separada para evitar que atrasos de exposição da webcam bloqueiem a interface do usuário ou o processador de pose.
5. **Estilo de Código e Nomenclatura:**
   - Classes em `PascalCase`, métodos e variáveis em `snake_case`, constantes em `UPPER_SNAKE_CASE`.
   - Utilize tipagem explicativa e docstrings concisas em português ou inglês compatíveis com o padrão existente.
   - Manipulação de caminhos exclusivamente via `pathlib.Path`.

---

## 🧪 Procedimento de Testes e Validação Obrigatória

Qualquer alteração realizada por um agente de IA deve ser validada executando:

```powershell
python LegacyPSCam_Sensor/test_suite.py
```

Todas as 9 suítes de teste integradas devem passar com sucesso (`9/9 PASSED`):
1. `ModularProjectStructure`: Validação dos pacotes `sensor/`, `ui/`, `assets/` e importações unificadas.
2. `ConfigManager`: Leitura, persistência e parsing de presets.
3. `KinectSharedMemory`: Tamanho exato (344 bytes), cabeçalho binário, paridade de seqlock e offsets dos joints.
4. `HandAnchorFilter`: Extrapolação 3D e 2D do vetor de antebraço.
5. `AdaptiveSmoother`: Filtragem suave em repouso vs resposta instantânea em alta velocidade.
6. `SkeletonCalibrator`: Convenções métricas de eixos do Kinect (X lateral correto, Y positivo para cima, Z ~2.0m).
7. `PoseTracker`: Resiliência contra timestamps duplicados em modo 60 FPS contínuo.
8. `TrackingOverlay`: Renderização estável sem exceções de tipos de dados.
9. `CameraManager`: Detecção de PnP e verificação de status do driver PSCam4Win.

---

## 🚫 Restrições Operacionais

- **Não altere dependências externas** a menos que estritamente solicitado pelo usuário. O projeto depende apenas de `opencv-python`, `mediapipe` e bibliotecas padrão (`tkinter`, `mmap`, `struct`, `threading`, `json`).
- **Não delete arquivos de modelos** (`models/pose_landmarker_lite.task`) ou binários de suporte (`Kinect for Legacy DLL/Kinect10.dll` e `tools/PSCam4Win-Setup.exe`).
- **Não bloqueie a thread principal do Tkinter:** Qualquer operação demorada de câmera ou tracking deve ser iniciada via thread dedicada (`threading.Thread(daemon=True)`).
- **Foco Exclusivo na PlayStation 4 Camera (PS4 Camera):** Ao lidar com recursos do PSCam4Win, mantenha o foco exclusivamente no hardware da PlayStation 4 Camera (chip OmniVision OV580 + sensores estéreo OV9713, 1280x800 @ 60 FPS, upload de firmware USB e câmera virtual). Ignore totalmente a câmera PS3 Eye ou periféricos do PS3.

---

## 📚 Manutenção da Documentação Técnica (Pasta docs/)

Sempre que um agente de IA realizar modificações relevantes no projeto, ele **DEVE obrigatoriamente atualizar a documentação técnica correspondente na pasta `docs/`**:

- **Novas funcionalidades ou ajustes de comportamento:** Atualize `docs/FEATURES.md` e `docs/README.md`.
- **Alterações de arquitetura, novos módulos ou fluxo de dados:** Atualize `docs/ARCHITECTURE.md`.
- **Mudanças em dependências, drivers, portas ou passos de inicialização:** Atualize `docs/SETUP.md`.
- **Novos testes, diretrizes de código ou refatorações:** Atualize `docs/DEVELOPMENT.md`.
- **Alterações no contrato binário, memória compartilhada, structs ou flags CLI:** Atualize `docs/API.md`.

> [!IMPORTANT]
> A documentação técnica deve refletir com 100% de precisão o estado real e atual do código. Nunca documente funcionalidades inexistentes como se estivessem prontas.

