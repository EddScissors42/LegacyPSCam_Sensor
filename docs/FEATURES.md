# ✨ Catálogo de Funcionalidades — Legacy PSCam Sensor

Este documento descreve detalhadamente o estado atual de todas as funcionalidades do **Legacy PSCam Sensor**, distinguindo com precisão o que está **Totalmente Implementado**, **Parcialmente Implementado** e **Planejado para o Futuro**.

---

## 📊 Matriz de Status das Funcionalidades

| Funcionalidade | Status | Arquivo Principal | Descrição |
|---|---|---|---|
| **Rastreamento Esquelético (20 Joints)** | ✅ Totalmente Implementado | `kinect_shared_memory.py` | Mapeamento exato de 20 articulações em 344 bytes. |
| **Rastreamento Multi-Tier (Corpo Parcial / Mesa)** | ✅ Totalmente Implementado | `pose_tracker.py` | Calibração em 3 camadas e sintetizador de membros inferiores para notebooks/mesas. |
| **Silhueta e Contorno Neon ("Sombrinha")** | ✅ Totalmente Implementado | `pose_tracker.py` / `tracking_overlay.py` | Máscara anatômica com contorno neon e preenchimento translúcido. |
| **Ponte de Imagem e Máscara (JMI1)** | ✅ Totalmente Implementado | `kinect_shared_memory.py` | Buffer de 1.3 MB (640x480 BGRA + 320x240 Player Mask) para o Just Dance. |
| **Ponte de Coach X (JXC1)** | ✅ Totalmente Implementado | `kinect_shared_memory.py` | Buffer de 28 bytes para posicionamento de coach no jogo. |
| **Integração PlayStation 4 Camera (Backend Nativo WinUSB)** | ✅ Totalmente Implementado | `sensor/ps4_backend/` / `camera_manager.py` | Backend próprio em espaço de usuário via `winusb.dll`, upload automático de firmware OV580, streaming isócrono em **1280x800 @ 60 FPS** e seleção de olho (**Olho Direito** padrão / **Olho Esquerdo**). |
| **Gerenciador Criptográfico de Firmware OV580** | ✅ Totalmente Implementado | `sensor/ps4_backend/firmware_manager.py` | Verificação estrita SHA-1/SHA-256 (`68.032` bytes), cache em `%ProgramData%\LegacySensor\Firmware` e download automático sob demanda. |
| **Instalação Automática de Associação WinUSB** | ✅ Totalmente Implementado | `sensor/ps4_backend/driver_installer.py` / `driver/legacy_pscam_device.inf` | Associação automática ao `WinUSB.sys` via `pnputil.exe` com elevação UAC pontual apenas quando necessário. |
| **Auto-Detecção de Hotplug e Reconexão** | ✅ Totalmente Implementado | `camera_manager.py` / `gui.py` | Monitoramento PnP de hardware via Win32 CfgMgr32 (< 3ms) com auto-seleção e atualização fluida sem congelar o menu. |
| **Máquina de Estados da PS4 Camera** | ✅ Totalmente Implementado | `camera_manager.py` / `gui.py` | Detecção em tempo real do ciclo de vida USB (Desconectada, Bootloader, Câmera Virtual e Pronta). |
| **Integração Webcams Padrão** | ✅ Totalmente Implementado | `camera_manager.py` | Suporte a webcams USB e embutidas em 30 e 60 FPS. |
| **Filtro Hand Anchor** | ✅ Totalmente Implementado | `pose_tracker.py` | Extrapolação do vetor de antebraço para mãos velozes. |
| **Suavização EMA Adaptativa** | ✅ Totalmente Implementado | `pose_tracker.py` | Filtro dinâmico sensível à velocidade (anti-jitter). |
| **Calibração de Escala e Eixos** | ✅ Totalmente Implementado | `pose_tracker.py` | Centralização dos quadris e conversão de eixos para o Just Dance. |
| **Interface Gráfica PlayStation 5 (Qt 6 / PySide6)** | ✅ Totalmente Implementado | `ui/gui_qt.py` / `ui/pages/` | UI inspirada no console PlayStation 5 com animações fluidas de deslizamento horizontal entre abas (`SlidingStackedWidget` com curvas cúbicas), cartões com sombras e cantos arredondados, pacote declarativo modular por página e painel sensível a estado (cartão PlayStation Move Emulator exibido apenas com DualShock 4 conectado). |
| **Painel Sensível a Estado (Balão de Desconexão Único)** | ✅ Totalmente Implementado | `ui/gui_qt.py` / `icons.py` | Quando desconectado, o balão com 'X' grande e botão contextual é o **único elemento exibido**. Ao conectar, transita automaticamente para os controles de vídeo e opções adicionais. |
| **Quality Presets & Opções Manuais de Tracking** | ✅ Totalmente Implementado | `ui/pages/tracking_page.py` / `pose_tracker.py` | Grade 2×2 de presets por hardware (**Performance**, **Balanced [RECOMMENDED]**, **High**, **Custom**) com troca automática para **Custom** ao editar **AI Model**, **Inference Quality** (`320p`/`Auto`/`640p`), **Silhouette Cutout** (`Fast`/`Accurate`) ou **Player Lock** (`Enabled`/`Disabled`). |
| **HUD de Jogo e Overlay OpenCV** | ✅ Totalmente Implementado | `tracking_overlay.py` | Renderização do esqueleto, silhueta e contadores reais de FPS. |
| **Interface de Linha de Comando (CLI)**| ✅ Totalmente Implementado | `main.py` | Flags `--start`, `--mode {pscam,webcam,ds4}` e `--camera`. |
| **Rastreamento Multi-Jogador (2P Duo) & Memória Anti-Swap** | ✅ Totalmente Implementado | `sensor/player_slot.py` / `pose_tracker.py` | Rastreia até 2 dançarinos simultâneos (P1 Azul e P2 Laranja Claro) via `JDP2` (664B) e `JMI2` (máscara indexada 1 e 2), com memória persistente de identidade (`LongTermIdentityProfile`) resistente a valsas, cruzamentos e saídas temporárias. |
| **Auto-Framing / FaceFollow PTZ** | ✅ Totalmente Implementado | `pose_filters.py` / `tracking_session.py` | Auto-framing digital com zoom suave (1.22x) e alinhamento de frustum 3D→2D (`warpAffine`) em modo 1P (desativado automaticamente em 2P para nunca cortar o segundo jogador). |
| **Emulador Nativo de PlayStation Move (ZCM2 para DS4)** | ✅ Totalmente Implementado | `sensor/psmove_shared_memory.py` / `tools/LegacyMove*.dll` | Emula um PlayStation Move nativo (`VID 0x054C / PID 0x0C5E`) diretamente na memória do jogo (`Legacy.exe` x86, `Legacy Lab.exe` x64 e `LegacyLab_Offline.exe` x64) alimentado pela IMU de 6 eixos do DualShock 4 (pegada vertical "joinha"), botões 1:1 e sincronia em tempo real da esfera RGB e vibração (Gold Moves) com a Light Bar do DS4. Substitui e remove integralmente o legado Virtual Phone. |
| **DualShock 4 & Controles Compatíveis (Nível A) [EXPERIMENTAL]** | ✅ Totalmente Implementado | `sensor/ds4_controller.py` / `ui/pages/ds4_page.py` | Driver nativo Bluetooth/USB HID (500+ Hz) com suporte a DS4 original, controles licenciados de terceiros (Hori, Nacon, Razer, Astro, Scuf) e clones/réplicas (ShanWan, DragonRise), calibração automática de zero-bias do giroscópio em repouso e diagnóstico de IMU congelado (0G). |
| **Utilitários de Telemetria Comparativa (Backend)** | 🔒 Backend Utilitário | `sensor/telemetry_benchmark.py` | Motor de parsing de CSVs e correlação cruzada preservado apenas no backend para diagnósticos offline (sem UI dedicada). |
| **Visão Estéreo (Stereo Vision) para PS4 Camera** | ✅ Totalmente Implementado | `sensor/stereo_matcher.py` / `ui/gui_qt.py` | Calibração de fábrica ($B=85.2\text{ mm}$), auto-alinhamento vertical dinâmico das lentes ($\Delta y$), triangulação 3D sub-pixel via Fluxo Óptico Piramidal (`PyrLK`, <0.5ms) e suavização temporal EMA da silhueta. |
| **Emulate Kinect & PS Move (Zero-File-Replacement Mode)** | ✅ Totalmente Implementado | `sensor/kinect_emulator.py` / `tools/Legacy10*.dll` / `tools/LegacyMove*.dll` | Emulação do sensor Kinect (`Legacy10.dll` x86 / `Legacy10_x64.dll` x64) e do controle PlayStation Move ZCM2 (`LegacyMove.dll` x86 / `LegacyMove_x64.dll` x64) diretamente na memória RAM do Just Dance Legacy, Legacy Lab e Legacy Lab Offline, sem alterar nenhum arquivo no disco do jogo. |
| **Camera Warm-Up em Background & Standby Throttling** | ✅ Totalmente Implementado | `sensor/camera_manager.py` / `ui/controllers/camera_controller.py` | Pré-negociação assíncrona da câmera em standby (<0.4% CPU) com desligamento assíncrono não-bloqueante (`CameraPrewarmCloser` + evento interrompível `_stop_event`), eliminando travamentos ao alternar de Webcam para DualShock 4 ou Phone Camera e reduzindo o tempo de `START TRACKING` de ~2.3s para ~0.3s. |
| **Lazy Loading Estendido PEP 562 & Startup Otimizado** | ✅ Totalmente Implementado | `sensor/__init__.py` / `ui/gui_qt.py` | Carregamento sob demanda de submódulos secundários (`phone_camera`, `psmove_shared_memory`, `ds4_controller`, `telemetry_benchmark`) para inicialização ultrarrápida da aplicação. |
| **Modo Headless (Sem Janela)** | ⏳ Planejado | `tracking_session.py` | Rastrear em background sem gastar GPU com janela gráfica. |

---

## 🔍 Detalhamento das Funcionalidades Implementadas

### 1. Sensor de Movimento Corporal Compatível com Kinect v1 (IPC Bridge)
- **Como funciona:** O jogo Just Dance PC espera receber os dados das 20 articulações do corpo no sistema de coordenadas métricas do sensor Kinect v1 original da Microsoft.
- **Implementação:** O `pose_tracker.py` calcula os pontos-chave (como o centro dos quadris na média entre quadril esquerdo e direito, a coluna na média entre ombros e quadris, e o centro dos ombros) e entrega um vetor de 20 tuplas `(X, Y, Z, Confiança)`.
- **Eixos Mapeados:**
  - `X`: Lateral (-1.0m à esquerda do sensor, +1.0m à direita do sensor).
  - `Y`: Vertical (+1.0m para cima, -1.0m para baixo).
  - `Z`: Profundidade em metros (centralizado na distância nominal de dança de 2.0m).

### 2. Integração Especializada com a PlayStation 4 Camera (Backend Próprio WinUSB — OV580)
- **Como funciona:** A PS4 Camera (incluindo a versão **PlayStation 4 Camera Slim**) é uma câmera estéreo equipada com o processador OmniVision OV580 e dois sensores OV9713, capaz de atingir 60 FPS em 1280x800 (ou até 240 FPS em 320x192) com amplo campo de visão horizontal.
- **Implementação (`sensor/ps4_backend/`):**
  - **Comunicação Direta em Espaço de Usuário (`winusb.dll`):** O `LegacyPSCam_Sensor` comunica-se diretamente com o dispositivo USB através do driver nativo `WinUSB.sys` da Microsoft, eliminando a dependência de aplicativos externos de bandeja (`PSCam4WinTray.exe`), DLLs de câmera virtual ou serviços em segundo plano.
  - **Gerenciamento e Upload Automático de Firmware (`PS4FirmwareManager`):** Ao detectar a câmera no estado de bootloader (`VID_05A9&PID_0580`), o sistema valida criptograficamente o `firmware.bin` (`68.032` bytes, SHA-1 `8b8a6621d358f6782c2e3b31aac2cdfb25102c00`, SHA-256 `09513d10...`) armazenado em `%ProgramData%\LegacySensor\Firmware\`, envia os blocos de 512 bytes via transferência de controle USB e dispara o comando de reboot (`0x5B`), aguardando a re-enumeração como `VID_05A9&PID_058B` (`MI_00`).
  - **Streaming Isócrono de Baixa Latência (`PS4CameraBackend`):** Mantém um anel assíncrono de 8 URBs Overlapped (`WinUsb_ReadIsochPipeAsap`) no endpoint `0x81`, negociando UVC YUY2 e ativando Auto-Exposure (`CT_AE_MODE_CONTROL = 0x02`) e Anti-Flicker 60Hz no ISP interno do OV580.
  - **Seleção de Olho e Arquitetura Dual-Stream:** Desempacota cada linha entregando simultaneamente os planos do **Olho Direito** (padrão) e **Olho Esquerdo**, permitindo alternar entre as duas lentes na interface gráfica e mantendo ambos os fluxos sincronizados com timestamps PTS para uso estéreo.

### 3. Visão Estéreo (Stereo Vision) para PlayStation 4 Camera
- **Como funciona:** Aproveita os dois sensores independentes OmniVision OV9713 espaçados por $85.2\text{ mm}$ na carcaça rígida da PS4 Camera, sincronizados linha a linha pelo hardware do processador OV580 a 60 FPS (1280x800) ou 120 FPS (640x400).
- **Implementação (`sensor/stereo_matcher.py` & `sensor/pose_tracker.py`):**
  - **Retificação Epipolar de Custo Zero e Luminância Direta (`StereoCalibrator` & `read_left_mono`):** Em geometria rígida de fábrica sem distorção, o retificador opera em modo identidade (<0.001 ms, zero-copy). O olho esquerdo entrega o plano de luminância diretamente do buffer YUY2 em <0.08 ms, eliminando remapeamentos bilineares e conversões BGR desnecessárias, sustentando 60 FPS cravados com modelo Lite / Competitive.
  - **Triangulação 3D Sub-Pixel de Tronco (`PyrLK` + Banda Epipolar 2D):** Realiza busca em banda 2D com interpolação parabólica seguida de refinamento por Fluxo Óptico Piramidal Lucas-Kanade (`cv2.calcOpticalFlowPyrLK`) sobre os **8 joints de tronco** (`0, 1, 2, 3, 4, 8, 12, 16`), reduzindo em ~75% o custo de CPU (~1,0 ms/frame em 1280x800) e ancorando a profundidade métrica da sala ($Z = \frac{f \cdot B}{d}$) sem introduzir saltos espúrios de profundidade (*Z-popping*) em punhos, mãos ou cotovelos rápidos.
  - **Auto-Calibração Epipolar Vertical Dinâmica (`vertical_offset_px`):** Mede e compensa automaticamente em background pequenas diferenças de inclinação vertical ($\Delta y$) entre a lente esquerda e a direita da unidade física da câmera, dispensando calibração com tabuleiro de xadrez.
  - **Suavização Temporal EMA na Silhueta (`_seg_prob_ema`):** Suaviza temporalmente o tensor de probabilidade da máscara de segmentação do MediaPipe antes da binarização, eliminando tremulações de ruído ISO em 60 FPS sem usar `StereoSGBM` denso.
- **Ativação Automática por Padrão:**
  - O modo **`Sub-Pixel PyrLK 3D` (`sparse_metric`)** é ativado automaticamente por padrão na PlayStation 4 Camera (removido da interface gráfica como opção manual), funcionando de forma transparente tanto com o **Olho Direito** quanto com o **Olho Esquerdo** selecionado como lente principal e mantendo 60 FPS cravados.

### 3.1 Sistema Modular "Person Lock-In" (`sensor/person_lock.py` & `sensor/pose_filters.py`)
- **Objetivo:** Fazer o rastreador "grudar" no dançarino ativo e jamais perder o esqueleto ou a silhueta em giros rápidos de 360°, oclusões momentâneas, passos largos ou quando outra pessoa passa pelo ambiente, mantendo **60 FPS cravados** (< 0.25 ms de custo combinado).
- **Arquitetura 100% Modular (Hot-Reload & Zero-Cost Bypass):**
  - Controlado pela chave mestra `person_lock_enabled` e pelas chaves individuais `inertial_coasting_enabled`, `dancer_lock_enabled`, `dancer_lock_roi_focus`, `face_follow_spin_fallback` e `face_follow_adaptive_zoom`. Quando desabilitado, cada módulo executa *short-circuit* imediato (0.000 ms), pronto para futuros controles de UI em hardwares modestos.
- **Os 3 Pilares Implementados:**
  1. **Predição Inercial em Micro-Quedas (`InertialCoastingFilter`):** Quando a rede neural perde o corpo por até `250 ms` (~15 frames a 60 FPS durante um giro de 360° ou *motion blur*), o filtro mantém `is_tracked = True` e projeta as 20 articulações 3D e 2D usando velocidade física amortecida ($\gamma = 0.82$), deslocando também a máscara de silhueta `320x240` e aplicando interpolação suave (*re-entry LERP*) por 3 frames ao readquirir o jogador.
  2. **Trava de Jogador Ativo por Cor e Espaço (`DancerIdentityLock`):** Memoriza um histograma 2D Matiz-Saturação (HSV 12x8 bins) da roupa/tronco do jogador e monitora a continuidade espacial da caixa delimitadora. Rejeita saltos impossíveis para objetos de fundo ou pessoas passando com outra cor de roupa, além de atenuar suavemente regiões periféricas distantes no buffer privado da IA (`apply_roi_focus`).
  3. **Auto-Framing Dinâmico de Corpo Inteiro (`FaceFollowPTZ` Aprimorado):** Inclui fallback anatômico anti-giro (extrapola a posição da cabeça pelo vetor `HipCenter -> ShoulderCenter` quando o rosto fica oculto de costas), deadzone central anti-trepidação e zoom adaptativo de corpo inteiro que abre o enquadramento automaticamente quando o jogador ergue os braços ou abre a base.

### 4. Filtro Hand Anchor, Centro de Palma e Proteção Anatômica
- **Problema resolvido:** Em coreografias de dança com giros rápidos ou mãos próximas ao tronco, as redes neurais frequentemente perdem a visibilidade dos dedos ou distorcem/dobram a ponta do dedo indicador em ângulos impossíveis (>90°), corrompendo o vetor 3D do antebraço e derrubando notas `PERFECT` para `GOOD`/`SUPER`.
- **Implementação:** O `PlayerSlotState` sintetiza `HandLeft`/`HandRight` no ponto médio ponderado entre `INDEX` e `PINKY` (alinhado ao centro da palma do Kinect v1). Em seguida, o `HandAnchorFilter` extrapola ao longo do vetor `cotovelo -> pulso` quando a confiança cai (`< 0.45`), limita estiramentos/colapsos implausíveis (`[4 cm, 16 cm]`) e corrige dobramentos invertidos de punho.

### 4.1 Suavização Dinâmica Anti-Jitter Desacoplada XY/Z (Adaptive Dynamic EMA) & Rastreamento Vertical (Agachamento/Salto)
- **Problema resolvido:** Filtros simples adicionam atraso em golpes rápidos ou deixam mãos tremendo em poses paradas; além disso, ruído no eixo Z monocular inflava a resposta de XY, e a ancoragem estática do quadril em `Y = 1.0m` mascarava agachamentos, *bounces* e saltos.
- **Implementação:**
  - O `AdaptiveSmoother` opera com compensação contínua de `dt`, *deadzone* de velocidade (`VEL_DEADZONE = 0.010m`), suavização desacoplada para XY e Z (piso mais firme em Z em repouso), mãos calmas em poses paradas (`<= 0.56`) com rampa instantânea até `0.96` em golpes rápidos e amortecimento escalonado por `dt` contra saltos espúrios de 1 frame (>35 cm).
  - O `CameraSpaceYTracker` mede o deslocamento vertical do quadril normalizado pela altura do tronco em câmera para transmitir agachamentos (`-0.42m`), *bounces* e saltos (`+0.30m`) preservando a geometria interna do esqueleto e mantendo `dy = 0` em uso na mesa.
  - O `apply_slot_snap` usa curva linear por partes $C^0$-contínua na zona morta, eliminando pequenos saltos laterais ao cruzar o centro da sala, e a síntese de pernas avalia esquerda e direita de forma independente (chutes ou oclusão de um tornozelo não sobrescrevem a outra perna).

### 5. Memória Compartilhada Seqlock Lockless Multi-Canal
- **Como funciona:** O `kinect_shared_memory.py` implementa o `KinectBridge`, orquestrando três buffers de memória compartilhada Windows em formato *seqlock*:
  1. `Local\LegacyWebcamKinectPose` (344 bytes): 20 articulações corporais consumidas por `NuiSkeletonGetNextFrame` no Just Dance PC.
  2. `Local\LegacyWebcamKinectImage` (1.305.632 bytes): Cabeçalho de 32 bytes + Frame BGRA 640x480 + Máscara do Dançarino 320x240 consumida por `NuiImageStreamGetNextFrame`.
  3. `Local\LegacyWebcamKinectCoachX` (28 bytes): Posição X da pista/coach.
- **Garantia de Não-Travamento:** A gravação usa a técnica de *seqlock*:
  - Ao iniciar a escrita, incrementa o número de sequência para um número ímpar.
  - Grava os bytes de forma atômica e em bloco único (`struct.pack`).
  - Ao concluir, incrementa a sequência para o número par subsequente.
  - O `Kinect10.dll` lê o bloco sem precisar travar mutexes do Windows, garantindo que o jogo Just Dance PC nunca congele mesmo sob alta carga de processamento.

### 6. Silhueta Sombreada e Contorno Neon ("Sombrinha")
- **Problema resolvido:** O jogo Just Dance PC necessita de um stream de máscara de profundidade do jogador para exibir a silhueta no HUD inferior e reconhecer que há um dançarino diante da câmera. Além disso, a prévia do sensor clássico exibia a silhueta translúcida acompanhando os movimentos.
- **Implementação:**
  - O `pose_tracker.py` gera uma máscara binária anatômica (`build_body_mask`) conectando os pontos-chave de tronco, membros e cabeça via polígonos e cápsulas dilatadas.
  - O `tracking_overlay.py` renderiza na prévia OpenCV uma silhueta semitransparente em tom escuro (`alpha = 0.30`) circundada por um contorno ciano/neon de alta visibilidade.
  - O `tracking_session.py` redimensiona e transfere essa máscara no canal `Local\LegacyWebcamKinectImage`, restaurando a silhueta e a detecção de presença do jogador dentro do próprio Just Dance PC.

### 7. Auto-Detecção de Hotplug e Reconexão Não-Bloqueante
- **Problema resolvido:** Conectar ou desconectar câmeras (Webcam ou PS4 Camera) exigia intervenção manual com cliques repetitivos no botão de atualizar ou causava congelamentos na interface durante sondagens síncronas do OpenCV.
- **Implementação:**
  - O `camera_manager.py` integra a API nativa do Windows `cfgmgr32.dll` (`CM_Get_Device_ID_ListW`) com filtro `CM_GETIDLIST_FILTER_PRESENT`, obtendo um snapshot de dispositivos presentes em apenas **~2.8 milissegundos**, sem gerar processos externos.
  - A interface `gui.py` executa essa verificação a cada 1.0 segundo. Ao detectar qualquer alteração de hardware PnP, despacha a enumeração detalhada do OpenCV para uma thread assíncrona (`threading.Thread(daemon=True)`).
  - Quando a câmera é reconectada, o menu a seleciona automaticamente e atualiza o dropdown sem nenhum travamento visual.

### 8. Máquina de Estados da PlayStation 4 Camera
- **Problema resolvido:** A PS4 Camera possui um ciclo de vida complexo no Windows: ao ser plugada a frio na porta USB 3.0, ela surge no modo bootloader (`05A9:0580`), o driver `PSCam4Win` faz o upload do firmware, a câmera reinicia como hardware ativo (`05A9:058B`) e registra duas instâncias virtuais DirectShow (`SWD\VCAMDEVAPI`). O usuário ficava sem saber em qual etapa o sistema se encontrava.
- **Implementação:**
  - `CameraManager.get_ps4_camera_state()` classifica a câmera em 6 estados atômicos:
    1. `NOT_INSTALLED`: Driver ausente em `C:\Program Files\PSCam4Win`.
    2. `DISCONNECTED`: Câmera desplugada da porta USB.
    3. `DRIVER_STOPPED`: Hardware conectado, mas aplicativo da bandeja fechado.
    4. `BOOTLOADER_UPLOADING`: Câmera detectada e recebendo firmware USB.
    5. `WAITING_VCAM`: Firmware carregado, aguardando registro DirectShow.
    6. `READY`: Câmera virtual ativa e pronta para streaming a 60 FPS.
  - A interface gráfica reflete essas transições instantaneamente com mensagens claras, cores de status dinâmicas e gerenciamento inteligente do botão de inicialização.

### 9. Perfis de Rastreamento Simplificados e Calibração Automática de Altura
- **Problema resolvido:** Sliders técnicos manuais (como fator EMA e confiança da rede neural) geravam dúvidas em jogadores casuais, e o slider de altura corporal causava confusão já que a normalização para o padrão métrico do Just Dance (1,75 m) é dinâmica e automática.
- **Implementação:**
  - **2 Perfis Simplificados em Cartões Interativos:**
    1. ⚡ **Competitivo (`competitive` — Lite AI, Padrão Recomendado)**: EMA 0.75 / Confiança 0.50 (Resposta ultrarrápida e 60 FPS estáveis em 1P e 2P).
    2. ⭐ **Equilibrado (`balanced` — Full AI)**: EMA 0.55 / Confiança 0.50 (Maior precisão esquelética sob demanda via `ModelManager`).
  - **Calibração de Altura Automática:** O slider manual de altura foi completamente removido da UI, substituído por um informativo visual claro explicando que o `SkeletonCalibrator` já calcula e redimensiona dinamicamente as proporções corporais a cada quadro para a escala padrão de 1,75 m do Just Dance.
  - **Gaveta Retrátil de Ajustes Avançados:** Permite que usuários avançados expandam os sliders milimétricos de EMA e Confiança quando desejado, com detecção automática do perfil "Personalizado".

### 10. Rastreamento e Calibração Multi-Tier para Corpo Parcial / Enquadramento de Mesa (Desk Framing)
- **Problema resolvido:** Jogadores que utilizam webcams integradas em notebooks ou webcams sobre a mesa frequentemente não possuem recuo suficiente na sala para enquadrar pernas e pés inteiros. Modelos de calibração rígidos exigiam tornozelos visíveis para estimar a escala; sem eles, a calibração falhava, o quadril perdia confiança e o `Kinect10.dll` rejeitava o jogador, gerando 0 pontos e ausência de silhueta no Just Dance.
- **Implementação:**
  - **Calibrador em 3 Camadas (`SkeletonCalibrator` Multi-Tier):**
    1. *Tier 1 (Corpo Inteiro / `full_body`):* Utiliza cabeça, tornozelos e quadris para estimar a altura real e mapear para a escala padrão de 1,75 m do Just Dance.
    2. *Tier 2 (Meio Corpo / `flexible_torso`):* Ativado quando os tornozelos saem do campo de visão; utiliza a envergadura de tronco (ombros até quadris) multiplicada pela proporção áurea anatômica humana (1,95x - 3,05x).
    3. *Tier 3 (Enquadramento Mesa / `upper_body`):* Ativado em enquadramentos muito próximos onde apenas cabeça e ombros estão visíveis. Utiliza a distância biacromial (largura dos ombros x 4.6) e distância cabeça-ombros para inferir a escala completa, ancorando a origem corporal onde os quadris anatomicamente estariam (`Y = 0.0m`).
  - **Sintetizador Dinâmico de Membros Inferiores (`process_frame`):**
    - Quando os quadris saem do enquadramento inferior, são sintetizados logo abaixo dos ombros com confiança alta (`0.85 * min(sh_l, sh_r)`), garantindo estado `TRACKED` (2) no `Kinect10.dll` para o `HipCenter` (`Joint 0`), que é essencial para o jogo manter o jogador ativo.
    - As pernas, joelhos e pés são sintetizados em postura ereta natural com confiança `0.35` (estado `INFERRED` / 1 no `Kinect10.dll`), satisfazendo o contrato do Just Dance sem penalizar a pontuação dos movimentos dos braços.
  - **Fusão de Máscara de Silhueta Robusta:**
    - O polígono anatômico do tronco é estendido até o limite inferior da imagem (`height - 1`) e fundido com a máscara de segmentação neural via `cv2.bitwise_or`. Isso assegura que o canal de silhueta `Local\LegacyWebcamKinectImage` (320x240) nunca envie uma máscara vazia, mantendo o dançarino visível no HUD do Just Dance mesmo sentado ou diante da mesa.
  - **Feedback Visual Dinâmico no HUD:**
    - O badge superior do HUD OpenCV exibe em tempo real o modo ativo: `CORPO INTEIRO (ATIVO)`, `MEIO CORPO (ATIVO)` ou `ENQUADRAMENTO MESA (ATIVO)`.

### 11. Otimização de Pacing a 30 FPS Fixos e Resolução de Timer de 1 ms no Windows
- **Problema resolvido:** A silhueta do dançarino dentro do Just Dance PC parecia travada a cerca de ~20 FPS com a DLL padrão do Kinect, enquanto tentativas ingênuas de acelerar a DLL para 60 FPS faziam o motor do jogo marcar todas as jogadas como "X" (erro).
- **Causa Raiz Identificada:**
  - A thread de ritmo em `0x10002320` no `Kinect10.dll` pulsa tanto o evento do stream de imagem quanto o evento do esqueleto (`0x1001e96c`).
  - O motor de pontuação do Just Dance PC é calibrado estritamente para a taxa fixa do Kinect v1 de **30 FPS**. Disparar o esqueleto a 60 FPS descompassa a velocidade angular das articulações e o mapa de batidas da música, invalidando todas as pontuações.
  - Ao mesmo tempo, o agendador padrão do Windows possui resolução de tick de 15,625 ms. Como `Sleep(33)` da DLL ultrapassa 2 ticks (31,25 ms), o Windows adormecia a thread por 3 ticks inteiros (`15,625 * 3 = 46,875 ms`), reduzindo a taxa real para apenas **21,33 FPS**.
- **Solução Implementada:**
  - **Preservação da DLL Original a 30 FPS (`0x21` / 33 ms):** Mantém a compatibilidade perfeita do motor de pontuação do Just Dance PC, sem erros de "X".
  - **Temporizador de Alta Resolução de 1 ms no Python (`set_high_resolution_timer`):** No [tracking_session.py](../sensor/tracking_session.py), ativamos `winmm.timeBeginPeriod(1)` e `ntdll.NtSetTimerResolution(10000, 1, ...)`. Com resolução de 1,0 ms no Windows, o `Sleep(33)` acorda exatamente a cada **33,6 ms**, elevando a taxa de 21 FPS para **30 FPS cravados**, que é o teto máximo e ótimo da engine do Just Dance.

### 12. Seleção Dinâmica de Dançarinos nos 6 Slots com Ancoragem de Quadril (1.0m)
- **Problema resolvido:** O jogo Just Dance PC travava o jogador automaticamente no Slot 4 (Dançarino Roxo), e passos laterais pelo ambiente físico não alteravam a seleção para outros slots (Slots 1 a 6).
- **Causa Raiz Identificada:**
  1. *Ordem de Suavização no Pipeline:* O `AdaptiveSmoother` estava sendo executado *após* a translação lateral e o encaixe de slots (`apply_slot_snap`). O filtro EMA suavizava o salto entre slots, amortecendo a transição e prendendo o jogador.
  2. *Altura dos Quadris:* O `SkeletonCalibrator` colocava o quadril em `Y = 0.0m` (nível do solo), fazendo o Just Dance interpretar que o jogador estava deitado ou fora da área útil de dança. A convenção métrica do Kinect v1 exige quadris a `Y = +1.0m` do chão.
  3. *Ganho Lateral Insuficiente para Webcams:* A amplitude lateral padrão não gerava deslocamento suficiente para cruzar os limites de $\pm 0.75\text{m}$ necessários para alcançar os extremos do palco (Slot 1 Azul e Slot 4/6). No centro ($X \approx 0.0$ a $+0.35\text{m}$), o jogo seleciona o início do grupo do Coach 2 (Slot 4 Roxo).
- **Solução Implementada:**
  - **Inversão da Ordem do Pipeline:** A postura anatômica é suavizada primeiro (`smoother.apply`), e em seguida a translação de sala (`apply_camera_space_translation`) e o encaixe decisivo (`apply_slot_snap`) são aplicados sobre o esqueleto suavizado.
  - **Elevação Métrica dos Quadris para 1.0m:** `k_y = -(y - origin_y) * scale + 1.0m`, posicionando quadris em 1.0m, cabeça em 1.75m e pés em 0.10m.
  - **Alcance Lateral Balanceado com Alinhamento Óptico:** `camera_x_range_m: 2.2`, `coach_assist_multiplier: 1.25`, `coach_assist_max_m: 1.20` e `slot_snap_gain: 1.25`. Passos naturais agora cobrem de $-1.15\text{m}$ a $+1.15\text{m}$, permitindo selecionar qualquer um dos 4 ou 6 slots de dançarinos sem estourar o campo de visão ou deslocar a cabeça para fora da tela.

### 13. Auto-Framing Digital (FaceFollow PTZ) e Alinhamento Óptico do Avatar de Seleção
- **Problema resolvido:** Na tela de seleção de dançarinos do Just Dance PC, o quadrado que exibe o rosto do jogador (avatar de seleção) aparecia deslocado para o lado da sala (por exemplo, na porta), embora se movesse quando o jogador movia a cabeça, e o rosto não ficava focado nem centralizado.
- **Causas Raízes Identificadas:**
  1. *Duplicação de Deslocamento pelo CoachX no Kinect10.dll:* O `KinectBridge` estava gravando `coach_x = hip_x` com `enabled = True` no canal `Local\LegacyWebcamKinectCoachX`. No entanto, os 20 joints no canal `Local\LegacyWebcamKinectPose` (`JDP1`) já continham o deslocamento lateral $X$. Ao ler `JDP1`, a função `0x1020` do `Kinect10.dll` somava `coach_x` novamente a todas as articulações, dobrando o desvio lateral ($X_{\text{final}} = X + \text{hip\_x}$).
  2. *Multiplicadores Excessivos de Amplitude Lateral:* A combinação de amplitude $2.8\text{m}$, multiplicador de $1.50$ e snap de $1.40$ (mais a duplicação do `CoachX`) multiplicava o desvio por até $11.76\text{x}$. Qualquer passo ou leve inclinação projetava a cabeça do jogador a mais de $2.0\text{m}$ para fora do enquadramento, caindo na borda extrema da imagem (na porta da sala).
  3. *Ausência de Auto-Framing (PTZ Digital):* O Just Dance recorta o quadrado do avatar a partir da imagem do sensor. Em webcams normais ou na PS4 Camera (amplo campo de visão), o rosto ficava distante e descentralizado.
- **Solução Implementada:**
  - **Desativação de Offset Automático no CoachX:** O `KinectBridge` agora grava `coach_x = 0.0` e `enabled = False`, eliminando a soma duplicada dentro do `Kinect10.dll` e mantendo a projeção do esqueleto 100% fiel à posição física do dançarino.
  - **Parâmetros Laterais Calibrados Opticamente:** Amplitude lateral calibrada para $2.2\text{m}$, com teto máximo de $\pm 1.20\text{m}$, garantindo que a projeção 3D da cabeça permaneça estritamente contida nos limites da imagem 640x480.
  - **Filtro FaceFollowPTZ (Auto-Framing com Zoom 1.22x):**
    - Rastreia dinamicamente os pontos faciais (`NOSE`, `LEFT_EAR`, `RIGHT_EAR`) com filtro EMA (`alpha = 0.20`) e deslocamento vertical (`y_bias = 0.06`).
    - Recorta e redimensiona suavemente o frame e a máscara enviados ao Just Dance (`Local\LegacyWebcamKinectImage`), mantendo o rosto do jogador focado, nítido e perfeitamente centralizado no quadrado de seleção de dançarinos.
    - Pode ser ativado ou desativado livremente pelo usuário na aba dedicada **"Experimental"** da interface gráfica.

### 14. Cards Modernos de Status de Conexão com Ações Contextuais
- **Melhoria de UX/UI:** Quando nenhuma PlayStation Camera ou Webcam USB estiver conectada, o balão de status torna-se o **único componente visível** na área de configurações, ocultando caixas de opções e opções adicionais até que uma câmera seja detectada.
- **Componentes Visuais e Layout:**
  - **Menu Superior Centralizado de 3 Abas:** As abas "Video Settings", "Tracking" e "Experimental" ficam perfeitamente centralizadas no topo do painel principal, cada uma com seu respectivo ícone supersampleado (`settings.svg`, `trackingicon.svg` e `lab.svg`).
  - **Ícones de Status Supersampleados (Pillow 4x LANCZOS):** Badge circular vermelho com "X" nítido e em negrito para desconexão/erro, badge âmbar para estados transitórios de firmware/driver, e badge verde com checkmark para conexão ativa.
  - **Diagnóstico em Tempo Real:** Exibe o status preciso do hardware e do serviço, como `"Driver Offline and Camera disconnected from USB Port"` ou `"Driver Online and Camera disconnected from USB Port"`.
  - **Botão de Ação Direto:** Botão plano estilizado com `PALETTE["blue_pastel"]` e texto em azul PlayStation (`PALETTE["blue_dark"]`) permitindo inicializar o PSCam4Win (`"Start PSCam4Win Driver"`) ou reescanear portas USB (`"Search for Webcams"`).
  - **Transição Fluida Conectado/Desconectado:** O painel de opções da câmera e as "Opções Adicionais" (HUD) só surgem na tela assim que o hardware/driver estiver no estado `READY`. Quando desconectado, voltam a ser recolhidos instantaneamente, mantendo a tela 100% limpa.

### 15. Menu "Experimental", Layout Espaçoso e Seta Dropdown (v0.2.4 Alpha)
- **Aba "Experimental" com Ícone de Laboratório (`lab.svg`):**
  - Introduzida nova aba superior navegável entre as abas principais, equipada com o ícone `lab.svg` renderizado com 4x supersampling anti-aliased.
  - Centraliza recursos experimentais e em teste, acomodando o **Auto-Frame (Digital PTZ)** com descrição detalhada de funcionamento.
- **Blocos com Contorno dos Cards de Calibração (Dispositivo no Topo + Resolução e FPS Abaixo):**
  - **Linha 1 (CAMERA DEVICE):** Bloco de largura total dedicado ao dispositivo de captura, eliminando aperto de nomes longos de câmeras USB. O botão de atualizar `↻` recebeu estilização personalizada com feedback de carregamento (`…`), sem causar flicker para a tela de câmera desconectada.
  - **Linha 2 (RESOLUTION & FRAMERATE):** Blocos de Resolução e FPS posicionados lado a lado logo abaixo do bloco de câmera, com divisão 50/50 e ampla área de respiro visual.
- **Ícone de Seta para Baixo (Dropdown Arrow):**
  - Adicionado o ícone vetorial anti-aliased `arrow_down.png` e regra `QComboBox::down-arrow` no stylesheet Qt, restaurando a seta indicadora em todos os menus suspensos de seleção.

### 16. Alinhamento de Controles, Aviso em Experimental e Auto-Reset de Aba (v0.2.5 Alpha)
- **Alinhamento e Pente Fino em "CAMERA DEVICE":**
  - Estrutura anatômica vertical unificada entre `block_dev`, `block_res` e `block_fps` (altura fixa de 90px, margens internas 14x10px e espaçamento vertical de 4px).
  - Título ("CAMERA DEVICE") e subtítulo ("Active Video Source") agora possuem as mesmas linhas de base dos blocos de Resolução e Framerate.
  - O botão de atualizar (`↻`, 34x32px) foi reposicionado como botão companheiro diretamente ao lado direito do menu suspenso de seleção de câmera (`self.cb_cameras`), mantendo alturas alinhadas ao pixel.
- **Card de Advertência Visual em "Experimental":**
  - Inserido callout em tons âmbar suaves com ícone `⚠️` informando com clareza o caráter experimental das opções avançadas.
- **Navegação Inteligente na Troca de Dispositivo:**
  - O método `_set_mode()` agora aciona `self._switch_tab("video")` automaticamente. Se o usuário estiver na aba de Calibração ou Experimental e alternar entre PlayStation Camera e Webcam Padrão na barra lateral, a janela retorna suavemente para a aba "Video Settings", exibindo de imediato as configurações do novo dispositivo.

### 17. Unificação Total em Qt 6, Anti-Clipping e Tradução em Experimental (v0.2.6 Alpha)
- **Desativação e Limpeza do Backend Tkinter (`gui.py`):**
  - O módulo legado `ui/gui.py` (1.552 linhas) foi removido em definitivo, consolidando a arquitetura em 100% PySide6 / Qt 6.
  - O ponto de entrada `main.py` e o pacote `ui` foram simplificados, removendo a flag legada `--gui` e instâncias de fallback desnecessárias.
- **Correção de Clipping nos Blocos de Resolução e FPS:**
  - Os blocos `block_res` e `block_fps` receberam `setWordWrap(True)` e altura ajustada para `108px`, permitindo que descrições técnicas de duas linhas caibam com perfeição em qualquer largura de janela (inclusive no tamanho mínimo de 920px).
  - As descrições em inglês foram aprimoradas para maior concisão e clareza técnica.
  - O parsing de presets foi reforçado com `MatchStartsWith` para sincronizar seleções contendo o sufixo `(Recommended)` sem quebrar a persistência em `config.json`.
- **Tradução da Advertência de Experimental para Inglês:**
  - O texto do callout de aviso da aba Experimental foi completamente traduzido para inglês fluente: *"CAUTION: Features here are under constant testing and development. They may not work as intended or may fail to function entirely, which could affect your gameplay experience."*
- **Faxina de Recursos Duplicados e Órfãos:**
  - Removidas as sobras `assets/camera.svg`, `assets/lab.svg` e `assets/icons/mode_.svg`. O pacote `assets` agora exporta diretamente os arquivos canônicos em `assets/icons/`.

### 18. Espaço "Additional Display Options" e Bloco "Camera Orientation" (v0.2.7 Alpha)
- **Padronização Conceitual de "Espaço":**
  - Os grandes blocos agrupadores da interface visual passam a ser denominados formalmente de **"espaços"** (espaço *Webcam Video Settings* e espaço *Additional Display Options*).
- **Novo Bloco "CAMERA ORIENTATION" no Espaço Additional Display Options:**
  - Integrado card com o mesmo contorno visual e anatomia dos blocos de Resolução e FPS (`border: 1px solid #E2E8F0; border-radius: 10px; background-color: #FFFFFF`).
  - Menu de seleção contendo as 4 rotações cardinais: `"0° (Padrão)"`, `"90° (Horário)"`, `"180° (Invertido)"` e `"270° (Anti-horário)"`.
  - Suporte completo no motor de captura assíncrona (`LatestFrameCamera`), aplicando `cv2.rotate` diretamente nos quadros antes da inferência de pose, viabilizando o uso de câmeras montadas de cabeça para baixo ou na vertical.
  - Atalho de teclado rápido (`O`) durante a dança para alternar instantaneamente a rotação da câmera.
  - Persistência automática em `config.json` via chave `camera_orientation`.
  - Altura padrão da janela atualizada para 640px para conforto ergonômico e respiro entre os espaços.

### 19. Scroll Area Responsivo e Proteção Anti-Colisão em Janelas Compactas (v0.2.8 Alpha)
- **Eliminação de Sobreposição entre Blocos:**
  - Corrigido o comportamento de colisão de widgets em janelas com altura reduzida (abaixo de 550px), onde a linha de Resolução e FPS sobrepunha o card de Dispositivo de Câmera.
  - Implementada restrição de altura mínima nos espaços (`webcam_card.setMinimumHeight(280)` e `display_card.setMinimumHeight(195)`), impedindo que o layout engine do Qt comprima os blocos internos uns sobre os outros.
- **Scroll Area Transparente e Minimalista (`QScrollArea`):**
  - Implementado wrapper de visualização com rolagem através de `_create_scroll_page()`, integrado a todas as abas principais (`Video Settings`, `Calibration` e `Experimental`).
  - Scroll vertical ativado automaticamente sob demanda (`ScrollBarAsNeeded`) e rolagem horizontal desativada (`ScrollBarAlwaysOff`).
  - Estilização moderna de barra de rolagem (8px de largura, trilha transparente, pill handle arredondado `#CBD5E1` com hover `#94A3B8`).
  - Margem lateral de respiro (gutter de 6px) para garantir que os contornos e sombras dos espaços não fiquem colados na borda da barra de rolagem.
  - Redução da altura mínima da janela para `500px` (`setMinimumSize(920, 500)`), conferindo total responsividade a monitores pequenos ou janelas redimensionadas.

### 20. Celular Virtual — Emulador JD Controller via Movimento da Mão (v0.2.9–v0.2.16 Alpha)
- **Problema resolvido:** Certas músicas e builds do Just Dance (como Just Dance 2022 PC Online / Dreyn) não possuem suporte a câmera/Kinect em todas as faixas ou operam exclusivamente via controle de mão / smartphone (protocolo WebSocket `/smartphone`). Além disso, ao entrar em músicas solo (como *Smalltown Boy*), o jogo podia registrar dois dançarinos simultâneos com a pontuação indo para o Jogador 2, caso a ponte Kinect estivesse alimentando esqueletos fantasmas ao mesmo tempo ou conexões WebSocket anteriores não fossem encerradas limpamente.
- **Soluções Implementadas (`sensor/virtual_phone.py`, `sensor/tracking_session.py` & `ui/gui_qt.py`):**
  - **Supressão Automática de Pose Kinect (Anti-Jogador Fantasma / Single Player Garantido):** Quando o Celular Virtual está ativado, o `tracking_session.py` silencia o canal de esqueleto do Kinect (`bridge.pose.write_empty()`), impedindo que a DLL do Kinect crie um dançarino redundante (Jogador 1) e garantindo que o celular virtual opere com exclusividade no jogo. O canal de vídeo/máscara continua ativo para o HUD do jogo.
  - **Desconexão Limpa RFC 6455 (Close Frame `0x88`):** O cliente WebSocket agora envia um frame de fechamento com código 1000 ao desconectar ou reiniciar, liberando imediatamente o slot no servidor CivetWeb do Just Dance para evitar que o jogo retenha o slot antigo e empurre novas conexões para o Jogador 2.
  - **Identificação Explícita do Slot na UI (`Player 1` / `Player 2`):** O status do Celular Virtual na interface agora indica explicitamente o slot de dançarino atribuído pelo jogo (ex: `Scoring Active • Player 1`), permitindo conferência imediata.
  - **Atalho de Validação (`Enter` / `Espaço`):** Pressionar Enter ou Barra de Espaço na janela de pré-visualização do sensor despacha o comando `VALID` através do celular virtual para confirmar seleções no menu sem precisar recorrer ao teclado como dispositivo de entrada adicional.
  - **Protocolo WebSocket Nativo UbiArt Multi-Geração (`v1` e `v2` com Auto-Detecção Estrita):**
    - Cliente WebSocket RFC 6455 puro (zero dependências externas) com auto-detecção de versão via pacote UDP de descoberta e negociação estrita de subprotocolo único:
      - **Just Dance 2020–2022 / Dreyn Mod:** Utiliza subprotocolo estrito `v2.phonescoring.jd.ubisoft.com` sobre canal seguro TLS/SSL (`wss://`). O servidor embutido CivetWeb requer correspondência textual exata do cabeçalho `Sec-WebSocket-Protocol`, evitando o erro `1002 CLOSE_PROTOCOL_ERROR`.
      - **Just Dance 2017 / 2018 (Legacy Offline):** Utiliza subprotocolo `v1.phonescoring.jd.ubisoft.com` sobre TCP plano (`ws://`).
    - **Prioridade para Localhost em Descoberta UDP:** O módulo de descoberta verifica primeiro `127.0.0.1` antes de fazer broadcast na sub-rede, eliminando conflitos de rotas com adaptadores de VPN (como Radmin) e conectando em menos de 2 ms no mesmo PC.
    - Executa a máquina de estados oficial de 5 etapas (`JD_PhoneDataCmdHandshakeHello` -> `JD_PhoneDataCmdHandshakeContinue` -> `JD_PhoneDataCmdSync` -> `JD_PhoneDataCmdSyncStart` -> `JD_PhoneDataCmdSyncEnd`), sincronizando o perfil do dançarino (`JD_ProfilePhoneUiData`) e identificando o dançarino como Jogador 1.
    - **Verificação Constante e Resiliência a Janela sem Foco (AFK):** Mantém a verificação ativa a cada 1s com auto-descoberta UDP (`6000`/`7000`) e preserva o socket aberto pacientemente mesmo quando a janela do Just Dance está sem foco (loop principal pausado), completando o pareamento no exato instante em que o jogador foca na janela do jogo.
    - Suporte dinâmico a `JD_ProfilePhoneUiData` (exibindo o nome do perfil do jogador conectado) e `JD_InputCollectionPhoneData` (`availableInput` com booleanos `touchOn: true/false`).
  - **Motor Fisico `HandAccelerometer` Calibrado via Telemetria Real (Ground Truth DS4):**
    - **Filtragem de Velocidade Pre-Derivada (Anti-Ruido de Segunda Ordem):** Aplica filtro exponencial de primeira ordem na velocidade 3D (tau = 45 ms) antes da derivacao da aceleracao linear, suprimindo picos de ruido numerico inerentes ao rastreamento optico.
    - **Filtro EMA Dinamico Balanceado:** Em repouso ou movimentos lentos (<= 0.20 m/s), opera com alpha = 0.35 para anular tremores e manter orientacao estavel; em passos rapidos (>= 0.85 m/s), eleva alpha para 0.72, capturando o tempo exato das batidas sem amplificar ruidos.
    - **Aceleracao Centrifuga / Rotacional:** Simula a forca centrifuga radial ao longo do antebraco durante giros e sweeps.
    - **Escalamento Fisico Calibrado (DS4 Ground Truth):** Calibrado diretamente contra a telemetria do DualShock 4 durante sessao real de danca na musica Smalltown Boy, alinhando o P95 em ~4.0G a 4.3G e a mediana em ~1.15G.
    - **Convencao de Eixos do Smartphone (Screen-Relative):** Mapeia a profundidade do Kinect para o eixo Z do smartphone (+Z apontado para o dancarino), corrigindo a orientacao da gravidade de repouso para (0.08, 0.38, 0.75) G.
    - **Limitacao de Magnitude Vetorial 3D (Teto Fisico de 7.0G):** O vetor resultante e limitado a 7.0 G, reproduzindo com precisao o teto maximo registrado pelo controle fisico (6.93 G) e impedindo saturacoes diagonais irreais.
  - **Gravador de Telemetria CSV Embutido (`Record Log`):**
    - Permite gravar em tempo real os dados de acelerometro 3D, velocidade da mao, alpha do filtro e coordenadas em `logs/vphone_accel_<timestamp>.csv` para analise diagnostica e comparacao direta com logs de celulares reais.
  - **Interface Unificada e Simplificada (Design Consistente com Calibracao):**
    - Chave geral **ON / OFF** com recolhimento dinamico: quando desativado, toda a secao de acelerometro e controles fica oculta para manter a interface limpa e direta.
    - Indicador de status em tempo real e leitura ao vivo do acelerometro 3D em linha dedicada abaixo do status.
    - **Visibilidade Condicional do 3D Acelerometro:** O mostrador de acelerometro 3D so e renderizado e visivel durante o rastreamento ativo (`START TRACKING`), ficando oculto quando inativo para manter o layout limpo.
    - IP e Porta ocultos da visao para evitar poluicao visual (mantendo valores padrao `127.0.0.1:8080` de forma transparente).
    - **Remocao do Slider de Sensibilidade da GUI:** A sensibilidade foi removida da interface grafica para evitar ajustes redundantes e operacoes incorretas, permanecendo gerenciada internamente com a calibracao fisica ideal (1.00x).
    - Botoes com contorno elegante (`border: 1px solid #CBD5E1`) para **Reconnect**, **Auto-Find**, **Skip Finish** e **Record Log**.
    - Atualizacao do cabecalho da sidebar para `"ooomaga :O"` e dica de DLL clarificada para `"Copy Kinect10.dll to the game folder (only for Legacy Offline PC)"`.
    - Tipografia de alto contraste com cores escuras explicitas (`#0F172A`) para "SCORING HAND", eliminando problemas de texto invisivel em temas escuros do Windows.

### 21. Modo DualShock 4 [EXPERIMENTAL] — Driver Bluetooth HID & Motion Scoring (v0.3.0 Alpha)
- **Objetivo:** Permitir o uso direto do controle DualShock 4 como controle de mão sem fio para dançar no Just Dance PC, aproveitando o sensor IMU Sixaxis interno (acelerômetro de 3 eixos e giroscópio de 3 eixos).
- **Implementação Técnica do Driver (`sensor/ds4_controller.py`):**
  - **Zero Dependências Externas (Native Win32):** Implementado 100% com `ctypes` utilizando as bibliotecas padrão do Windows (`setupapi.dll`, `hid.dll` e `kernel32.dll`), sem exigir pacotes externos adicionais.
  - **Enumeração Automática de Interfaces HID Bluetooth:** Busca pelas interfaces registradas sob a GUID de dispositivo HID (`{4d1e55b2-f16f-11cf-88cb-001111000030}`) filtrando por Sony Interactive Entertainment (`VID 0x054C`) e modelos DS4 v1/v2 (`PID 0x05C4` e `PID 0x09CC`).
  - **Compatibilidade Dual HID (Relatório Padrão 0x01 e Estendido 0x11):**
    - Suporte híbrido transparente para ambos os modos do driver Bluetooth do Windows: processa nativamente o relatório padrão `0x01` (64 bytes com IMU nos offsets 13 a 25 e bateria no byte 30) e o relatório estendido `0x11` (78 bytes com IMU nos offsets 15 a 27 e bateria no byte 32).
    - Suporte adaptativo de Output Report: detecta dinamicamente via `HidP_GetCaps` o tamanho esperado pelo driver (`32 bytes` para relatório `0x05` ou `78 bytes` para `0x11` com CRC-32), garantindo que vibração (rumble) e lightbar funcionem sem erros de parâmetro (`ERROR_INVALID_PARAMETER`).
    - Configura a barra de luz (Lightbar) para o tom icônico **PlayStation Blue** (`RGB: 0, 67, 156`).
  - **Taxa de Amostragem Ultrarrápida (~250 a 600 Hz):** Leitura assíncrona contínua via thread dedicada com baixíssima sobrecarga de CPU, capturando centenas de amostras por segundo.
  - **Escala Física e Orientação:**
    - Escala bruta de hardware de 8192 LSB por 1.0G traduzida em forças G reais.
    - Mapeamento coordenado para o protocolo de pontuação do Just Dance (eixos lateral X, vertical Y e longitudinal Z).
  - **Isolamento de Botões Anti-Missclick (Uso Exclusivo do Sensor):**
    - Para evitar que o dançarino pause ou saia da música acidentalmente ao segurar o controle com firmeza ou trocar de pegada durante passos rápidos, o envio de comandos de jogo através dos botões físicos foi desativado. Apenas o sensor inercial (acelerômetro 3D) alimenta a pontuação da dança.
  - **Desvinculação Completa de Câmera no Modo DualShock 4:**
    - Nenhuma webcam ou PlayStation Camera é inicializada ou aberta ao iniciar o tracking com o controle. O pipeline de hardware de vídeo permanece totalmente desligado, economizando CPU/energia e garantindo que o LED de privacidade da câmera permaneça apagado.
  - **Identidade Visual e Proporção Vetorial dos Ícones:**
    - O ícone do DualShock 4 na barra lateral utiliza `officialdualshock.png` com renderização supersampled e fundo transparente.
    - O ícone da Standard Webcam utiliza o vetor `webcam.svg` com preservação estrita de proporção 1:1 (`QRectF` centralizado em `render_svg_icon_pil`), impedindo distorções ou aspecto achatado/gordo.
    - Pasta `assets/` reorganizada categoricamente em `assets/icons/` e `assets/fonts/`.
  - **Feedback Háptico (Vibração / Rumble):**
    - Suporte a pulsos de vibração de alta e baixa frequência nos motores esquerdo e direito, com confirmação háptica ao conectar e teste interativo na interface.
  - **Telemetria de Bateria:** Leitura em tempo real do nível de carga (0% a 100%) e status de carregamento a partir dos relatórios HID.
  - **Janela de Telemetria e Dança (`run_ds4_tracking_session`):**
    - Janela gráfica estilizada com indicadores em barras das forças G em 3 eixos (`ACCEL X`, `ACCEL Y`, `ACCEL Z`), magnitude total de aceleração (`TOTAL G-FORCE`), percentual e status de carregamento da bateria, taxa de atualização HID em Hz e status de conexão com o Just Dance PC.
    - **Teclas e Controles de Navegação:**
      - `[L1] / [R1]` no DualShock 4 (ou `[` / `]` e `A` / `D` no teclado): Alterna ciclicamente o Coach / NPC selecionado na sala de dança (`JD_ChangeCoach_PhoneCommandData`), com pulso de vibração tátil de confirmação no controle. Compatível tanto com Just Dance 2020–2022 quanto Just Dance 2017/2018 Legacy (detecção de `JD_PhoneUiLobby` e proteção automática para faixas Solo com 1 coach).
      - **Botões Frontais (✕, ○, △, □) Desmapeados por Segurança:** Para prevenir toques acidentais e missclicks ao segurar firme o controle durante passos velozes de dança, o botão X não dispara comandos no controle. Confirmações de menu podem ser feitas pelo teclado (`Enter` / `Space`).
      - `[Q]`: Encerra o rastreamento e fecha a janela de telemetria de forma limpa.
      - `[R]`: Reconecta imediatamente o controle DualShock 4 via Bluetooth ou USB com confirmação de vibração tátil.

### 22. Polimento de UI, DualShock 4 Desconectado & Atalho "Skip Finish" (v0.3.1 Alpha)
- **Atalho "Skip Finish" ao lado de Test Rumble e Reconnect:** Posicionado na aba do DualShock 4 junto aos botões rápidos de ação com a dica/tooltip `"for Just Dance 2022 phone tutorial"`, permitindo avançar instantaneamente pelo tutorial de smartphone do Just Dance 2022.
- **Balão de Desconexão do DualShock 4:** Quando nenhum controle DS4 estiver conectado via Bluetooth ou USB, a interface exibe um balão de status vermelho com ícone de erro e instruções para ligar o controle, ocultando os controles avançados e mantendo o aviso experimental no topo.
- **Aviso Informativo no Modo DualShock 4:** Incluído no balão de aviso: *"Esse modo de controle automaticamente usa o metodo experiemental Celular virtual, problemas podem acontecer."*
- **Bloqueio de Acesso à Aba Experimental em Câmeras Desconectadas:** Quando uma webcam ou a PlayStation Camera estiver desconectada ou inacessível, a aba Experimental fica inativa e esmaecida (com cursor proibido), prevenindo configurações inconsistentes sem sensor de vídeo presente.
- **Ativação Inteligente com Auto-Conexão:** Ao acionar "Skip Finish", o sistema automaticamente assegura que o cliente WebSocket UbiArt esteja habilitado (`set_enabled(True)`), atualiza a interface e dispara a sequência de bypass `PHONE_FTUE_FINISH` por 4 segundos contínuos para garantir a transição de telas no jogo.

### 23. Compatibilidade Total USB/Bluetooth e Release Oficial (v0.4.0 Alpha)
- **Compatibilidade DualShock 4 via USB e Bluetooth:** O driver HID Win32 em `sensor/ds4_controller.py` suporta conexão tanto sem fio (Bluetooth HID Reports 0x11/0x05) quanto com fio via cabo USB (Report 0x01 a 250 Hz com envio de relatórios de saída via `HidD_SetOutputReport` para contornar a ausência de endpoint interrupt OUT no Windows).
- **Auto-Conexão e Separação de Status USB / Bluetooth:** A interface agora detecta imediatamente se o DualShock 4 foi conectado via cabo USB ou emparelhado via Bluetooth, exibindo `Status: Connected on USB` ou `Status: Connected via Bluetooth` com taxa de amostragem em tempo real e bateria. O painel de configurações (mão rastreada, sensibilidade, teste de vibração e atalhos) aparece automaticamente assim que o controle é conectado na USB, sem necessidade de iniciar o tracking previamente.
- **Janela de Rastreamento DS4 com Texto "Switch Coach":** No HUD inferior da janela OpenCV do modo DualShock 4, a legenda de controle para os botões L1/R1 foi padronizada para `[L1/R1] Switch Coach`.
- **Compilação de Release Standalone sem Ícone Customizado:** Empacotamento PyInstaller autônomo com executável padrão do Windows (`icon=None`), runtime hook para isolamento do MediaPipe e pipeline de CI/CD via GitHub Actions.

### 24. Correção Multi-Geração do Celular Virtual & Mapeamento Seguro de Botões (v0.4.9 Alpha)
- **Auto-Detecção Estrita de Subprotocolo UbiArt:** Descoberta UDP (`phonescoring.jd.ubisoft.com`) com detecção dinâmica do protocolo retornado pelo jogo:
  - `v2.phonescoring.jd.ubisoft.com` com WSS/TLS exclusivo para Just Dance 2020–2022 (evita erro de `1002 CLOSE_PROTOCOL_ERROR` gerado pelo parser do CivetWeb).
  - `v1.phonescoring.jd.ubisoft.com` com WS plain TCP para Just Dance 2017/2018 Legacy Offline.
  - Prioridade para conexão direta em `127.0.0.1` antes de broadcast na sub-rede, eliminando interferências com adaptadores de VPN (como Radmin).
- **Seleção de Coach / NPC Confiável no Just Dance 2018:**
  - Extração de coaches diretamente da classe `JD_PhoneUiLobby` do Just Dance 2018.
  - Proteção automática para músicas solo (1 coach) evitando envio de índices inválidos.
- **Proteção Anti-Missclick no DualShock 4:**
  - Botões frontais (Cross/X, Circle, Triangle, Square) desmapeados no controle físico para impedir que a pegada firme durante passos rápidos de dança envie comandos indevidos e derrube a conexão. Confirmações de menu permanecem no teclado (`Enter` / `Space`).

### 25. Benchmark de Telemetria Comparativa (Câmera vs DS4) & Calibração Adaptativa
- **Detecção Automática da Música e Ciclo de Pontuação:**
  - O Celular Virtual extrai dinamicamente o identificador da música (`mapName` ou `songName`, ex: *Levitating*, *SaveYourTears*, *Believer*) enviado pelo Just Dance 2022 no pacote `JD_PhoneUiSetupData`.
  - Monitora os eventos de início (`enable: true`) e término (`enable: false`) da dança através de `JD_EnableScoringPhoneData` e `JD_SmartphoneEvent_ScoringActivationChanged`.
- **Auto-Gravação Sincronizada (Auto-Record):**
  - Opção na interface para iniciar a gravação de telemetria no exato milissegundo em que a música começa e salvar/fechar automaticamente o log CSV quando a música termina.
  - Nomeação automática padronizada: `logs/[mapName]_[source]_[timestamp].csv`, marcando a origem dos dados (`source: camera` ou `source: ds4`).
- **Motor de Benchmark e Comparador de Curvas (`sensor/telemetry_benchmark.py`):**
  - Carrega e correlaciona dois arquivos de log da mesma música (um dançado com a Câmera e outro com o DualShock 4).
  - Alinhamento temporal automático via correlação cruzada (*cross-correlation*), compensando eventuais atrasos de início da dança.
  - Cálculo de métricas analíticas: correlação de Pearson (%), atraso/latência temporal média (ms), pico de aceleração G máximo (Câmera vs DS4) e percentil 95 (P95).
  - Cálculo da sensibilidade recomendada para calibrar o ganho da câmera perfeitamente à intensidade física do controle:
    $$\text{Sensibilidade Sugerida} = \text{Sensibilidade Atual} \times \left( \frac{\text{Pico Dinâmico DS4}}{\text{Pico Dinâmico Câmera}} \right)$$
- **Diálogo Gráfico de Benchmark (`TelemetryBenchmarkDialog` & `TelemetryBenchmarkChart`):**
  - Janela integrada no estilo PlayStation com listagem automática de sessões prontas para comparação ou busca manual de arquivos CSV.
  - Gráfico 2D renderizado com `QPainter` (antialiasing e suporte a High-DPI), plotando sobrepostas a curva de verdade terrestre do DualShock 4 (PlayStation Blue) e a curva de rastreamento da Câmera (Laranja/Âmbar).
  - Botão com 1 clique para aplicar a sensibilidade sugerida diretamente nas configurações ativas.
- **Calibração Adaptativa em Tempo Real (`AdaptiveCalibrationTuner`):**
  - Ingestão contínua dos feedbacks de pontuação do Just Dance (*PERFECT*, *SUPER*, *GOOD*, *OK*, *MISS*, *YEAH*).
  - Ajuste suave e dinâmico da sensibilidade durante a coreografia caso o jogador esteja se movendo velozmente mas recebendo notas *OK* ou *GOOD*.
- **Integração Completa na Interface do Modo DualShock 4:**
  - A aba **Experimental** agora é exibida também no modo de controle DualShock 4, posicionada de forma limpa ao lado de `Controller Settings`.
  - No modo DualShock 4, o checkbox do **Celular Virtual** permanece ativado e desabilitado (cinza/bloqueado), indicando visualmente que o controle físico utiliza a ponte de pontuação do celular virtual por padrão sem permitir desmarcação acidental.
  - Disponibiliza todos os controles de telemetria, detecção de música ativa, botão de Benchmark e opções de auto-gravação diretamente no fluxo de uso do DualShock 4.
- **Seção Dedicada de Benchmark na Interface Experimental:**
  - O utilitário de benchmark agora possui um bloco próprio e independente (`Telemetry Benchmark (Auto-Capture & Compare)`), desacoplado da caixa do Celular Virtual.
  - **Watcher Automático de Dança:** Ao marcar a opção, o sensor fica em prontidão ativa e inicia a gravação de telemetria no instante em que a música começa no Just Dance (`JD_EnableAccelValuesSending_ConsoleCommandData` ou `gameplaySetup`), sem necessidade de gravação manual.
  - **Detecção Híbrida de Música Ativa (WebSocket + Memória de Processo):** Caso o pacote `setupData` do jogo omita o `mapName` durante a reprodução, o sensor varre a memória do processo Just Dance em ~2.8ms localizando a stream ativa `/map/<MapName>/...webm` e formata o título legível da música em tempo real.
  - Exibe o HUD de status da música ativa (`Active Song: ... [Scoring Active]`) e botões dedicados de Benchmark e Acesso à Pasta de Logs com tipografia sóbria e limpa (sem emojis).
- **10 Suítes de Testes Automatizados:** Suíte 10 integrada em `test_suite.py` cobrindo parsing de CSV, auto-gravação, detecção de processo e mapa em memória, ciclo de vida de músicas, correlação de benchmark e adaptação de sensibilidade (`10/10 PASSED`).

### 26. Modularização do Pacote UI, Correções de Ciclo de Vida e Higienização (v0.4.11 Alpha)
- **Modularização de `ui/` (`ui/widgets.py` e `ui/benchmark_dialog.py`):**
  - Componentes reutilizáveis de interface (`pil_to_qpixmap`, `SlidingStackedWidget`, `DeviceNavCard` e `CalibPresetCard`) extraídos para `ui/widgets.py`.
  - Diálogo comparador e gráfico vetorial 2D (`TelemetryBenchmarkChart` e `TelemetryBenchmarkDialog`) extraídos para `ui/benchmark_dialog.py` com tipagem explícita (`typing.List`, `Dict`, `Optional`, `Any`) compatível com Python 3.10–3.15.
- **Sincronização de Parada e Encerramento Limpo (`closeEvent` & `stop_event`):**
  - `LegacySensorQtGUI` agora gerencia `self._tracking_stop_event` e o repassa a `run_tracking_session`, garantindo encerramento ordenado da sessão e desconexão limpa do DualShock 4 ao fechar a aplicação.
  - Corrigida a restauração do texto do botão principal ao finalizar uma sessão no modo DualShock 4 (`camera_mode == "ds4"`).
- **Simetria de Atalhos na Janela de Rastreamento (`tracking_session.py` & `tracking_overlay.py`):**
  - A tecla `[O]` (rotação de orientação de câmera 0°/90°/180°/270°) e as teclas `Enter`/`Espaço` (comando `VALID` no Celular Virtual) funcionam de maneira simétrica durante todo o loop de captura e constam no banner inferior do HUD.
- **Consolidação de Configuração Padrão e Limpeza de Recursos:**
  - `DEFAULT_CONFIG` em `sensor/config_manager.py` consolidado com todas as chaves persistidas pela aplicação (`camera_orientation`, `ds4_hand`, `ds4_sensitivity`, `benchmark_auto_record`, `virtual_phone_auto_record`, `virtual_phone_adaptive`).
  - Removidos ícones legados não utilizados (`camera.svg`, `dualshock4.jpg`) e corrigida a resolução de `MODELS_DIR` para builds congelados PyInstaller (`_MEIPASS`).

### 27. Seleção Dinâmica dos Modelos MediaPipe Lite e Full nos Perfis de Precisão
- **Integração dos 2 Modelos Oficiais (`models/pose_landmarker_{lite,full}.task`):**
  - **Competitive (`competitive`) ➔ `lite`:** Usa `pose_landmarker_lite.task` (EMA 0.75 / Conf 0.45) para latência mínima e máxima taxa de quadros (60+ FPS cravados na CPU).
  - **Balanced (`balanced`) [RECOMMENDED] ➔ `full`:** Usa `pose_landmarker_full.task` (EMA 0.55 / Conf 0.50) para o melhor equilíbrio entre estabilidade anatômica, rastreamento de mãos e desempenho.
- **Remoção do Modelo Heavy:** O modelo `pose_landmarker_heavy.task` (~30.6 MB) e o preset *Ultra Stable* foram removidos para manter o pacote ultraleve e focado em alta taxa de quadros, com fallback automático para `full` caso um `config.json` antigo referencie `heavy` ou `stable`.
- **Resolução e Fallback Seguros:** `_resolve_model_path(model_variant)` seleciona o modelo correspondente (incluindo builds PyInstaller `_MEIPASS`) com fallback automático para `lite` caso algum arquivo `.task` não esteja disponível.

### 28. Expansão DualShock 4: Suporte a Controles de Terceiros e Clones (Nível A) e Diagnóstico IMU (v0.5.3 Alpha)
- **Ampla Compatibilidade com Controles de PS4 (Nível A):**
  - Suporte estendido para além do DualShock 4 original da Sony (`0x054C`), adicionando identificação e aceitação direta de controles de terceiros licenciados:
    - **Hori:** PS4 Fighting Commander, Mini Gamepad (`0x0F0D`).
    - **Nacon:** Revolution Pro Controller 1, 2 e 3 (`0x146B`).
    - **Razer:** Raiju Ultimate e Raiju Tournament (`0x1532`).
    - **Astro:** C40 TR Controller (`0x9886`).
    - **Scuf:** Vantage e Impact (`0x2E95`).
    - **Qanba:** Controles arcade e pads PS4 (`0x2C22`).
    - **Mad Catz:** FightPad Pro (`0x0738`).
  - Reconhecimento de chipsets comuns em réplicas/clones genéricos sem fio:
    - **ShanWan:** Chips comuns em réplicas de DS4 (`0x2563`).
    - **DragonRise:** Chips genéricos USB/Bluetooth (`0x0079`).
- **Modo Permissivo Configurável (`ds4_permissive_mode`):**
  - Adicionado toggle visual na aba DualShock 4 da interface Qt 6 e chave correspondente em `config.json` (`ds4_permissive_mode: True` por padrão).
  - Quando ativado, permite que qualquer controle HID compatível com o layout de relatório do DualShock 4 seja enumerado e aceito.
  - **Proteção contra Falsos Positivos:** Controles Microsoft Xbox (`VID 0x045E`) são explicitamente bloqueados por blacklist interna, pois não possuem sensores de movimento físicos (acelerômetro/giroscópio).
- **Detecção e Nomenclatura Automática (`detect_controller_name`):**
  - O sistema identifica automaticamente a marca/modelo do controle a partir do ID do dispositivo e exibe seu nome exato na interface (ex.: *"Razer Raiju (PS4)"*, *"ShanWan DS4 Clone"* ou *"Generic / Clone DS4"*), tanto no card de status da UI quanto no HUD da sessão OpenCV.
- **Diagnóstico Automático de Sensor IMU Travado (`imu_frozen`):**
  - Controles piratas ou réplicas muitas vezes conectam por Bluetooth com sucesso, mas seus firmwares não transmitem os bytes do acelerômetro pelo ar, gerando um vetor constante de $0.0G$ (a gravidade terrestre normal em repouso deve registrar sempre $\sim 1.0G$).
  - O driver analisa a magnitude do acelerômetro em tempo real. Se registrar magnitude $< 0.05G$ continuamente por 50 leituras consecutivas, o estado `imu_frozen` é ativado.
  - A interface gráfica e o HUD de rastreamento exibem um aviso em destaque em vermelho alertando o usuário: `"[!] IMU SENSOR FROZEN (0G) — Conecte via cabo USB!"`, orientando o uso do cabo para recuperar o stream de aceleração física.

### 29. Desativação e Ocultação do Telemetry Benchmark na Interface Gráfica (v0.5.4 Alpha)
- **Remoção Visual da UI:**
  - O bloco visual dedicado de Benchmark de Telemetria (`self.benchmark_box`), seus botões de comparação gráfica e toggles de auto-captura foram removidos da árvore de exibição da aba Experimental (`page_exp`), simplificando e limpando o painel de configurações para o usuário final.
- **Desativação Segura por Padrão:**
  - Configurações persistidas em `config.json` e `DEFAULT_CONFIG` (`benchmark_auto_record: false` e `virtual_phone_auto_record: false`) garantem que o sistema não inicie gravação contínua em segundo plano sem necessidade.
- **Preservação Integral do Código (Sem Exclusão):**
  - Todo o motor matemático de parsing de CSVs, interpolação temporal, correlação cruzada e ganho sugerido (`sensor/telemetry_benchmark.py`), bem como a janela de renderização gráfica vetorial (`ui/benchmark_dialog.py`), permanecem 100% íntegros, testados e funcionais no repositório.
  - Os objetos continuam instanciados e conectados internamente no controlador Qt, permitindo que o recurso seja reativado no futuro sem necessidade de reimplementação.


### 30. Emulate Kinect (Zero-File-Replacement) — Sempre Ativo Automaticamente (Just Dance Legacy 32-bit)
- **Zero-File-Replacement Mode (`sensor/kinect_emulator.py`):**
  - Permite jogar Just Dance PC (Legacy Offline 2018) sem precisar substituir o `Kinect10.dll` original de 14.9 MB do Microsoft Kinect SDK v1.8 na pasta do jogo.
  - O daemon em segundo plano (`KinectEmulatorDaemon`) monitora a inicialização dos executáveis 32-bit (`Legacy.exe` e `JustDance.exe`).
  - Injeta remotamente a biblioteca proxy `tools/Legacy10.dll` via `VirtualAllocEx`, `WriteProcessMemory` e `CreateRemoteThread(LoadLibraryW)`.
  - Sobrescreve em tempo real a Import Address Table (IAT) do processo para os 8 ordinais originais do Kinect (`16, 5, 6, 21, 22, 9, 17, 26`), roteando as chamadas para os canais de memória compartilhada (`JDP1`, `JDP2`, `JMI1` e `JMI2`) do Legacy PSCam Sensor.
  - Inclui diagnóstico explícito e sem spam (`_log_diag_once`) para `ERROR_ACCESS_DENIED (5)` caso o jogo seja executado como Administrador e o sensor não.
- **Sempre Ativo e Independente:**
  - Permanece **sempre ligado automaticamente** em segundo plano desde a inicialização da aplicação.
  - Coexiste livremente com o **Virtual Phone Controller**.

### 31. Session Logger & Telemetria de Dança em Tempo Real (v0.8.1 / Backend)
- **Ciclo de Vida na Inicialização (Startup Reset):**
  - Ao abrir o aplicativo, o `SessionLogger` limpa os arquivos de log anteriores em `logs/`, criando uma nova sessão limpa (`logs/session.log` e `logs/session_telemetry.csv`) para evitar acúmulo de arquivos no disco.
  - Preserva automaticamente a sessão anterior em `logs/session_previous.log` como medida de segurança contra reaberturas acidentais logo após um bug report.
- **Cabeçalho Diagnóstico Completo de Sistema e Hardware:**
  - Registra a versão do Windows (Build/Versão), modelo do processador, contagem de núcleos, memória RAM física total e disponível via API Win32 `GlobalMemoryStatusEx`, runtime Python (PE compilado vs script interpretado) e versão do aplicativo.
- **Mapeamento e Transições de Controle em Tempo Real:**
  - Registra o controle ativo em uso: **DualShock 4** (USB ou Bluetooth, VID/PID, nível de bateria, clone vs oficial), **Virtual Phone** (pareamento WebSocket) ou **Câmera Óptica** (PlayStation 4 Camera ou Webcam USB).
  - Captura eventos de botões físicos do controle (L1/R1 de troca de coach) e mudanças de música detectadas pelo processo do jogo.
- **Streaming de Telemetria de Dança (CSV Assíncrono):**
  - Iniciado imediatamente a partir do clique em `START TRACKING`.
  - Gravação de alta frequência e thread-safe com buffer em lote (batching) a cada 100ms, registrando acelerações 3D ($a_x, a_y, a_z, |G|$), velocidade da mão ($v$), coordenadas dos joints principais (ombro, cotovelo, pulso, mão), FPS da câmera, FPS de inferência e notas de feedback do jogo com overhead $< 0,1\%$ de CPU.
- **Captura Global de Exceções e Crashes:**
  - Instalação de hooks para `sys.excepthook` e `threading.excepthook`, garantindo que eventuais falhas graves gravem o traceback completo com flush imediato no disco.
- **Botão `Open Logs Folder` na Barra Lateral:**
  - Botão de ação rápida (`btn_secondary`) posicionado na barra lateral imediatamente acima dos créditos de rodapé, abrindo a pasta `logs/` no Windows Explorer com 1 clique para agilizar o envio de relatórios de diagnóstico e arquivos de telemetria.

### 32. Sub-sistema Modular de Person Lock-In, Smart PTZ Auto-Framing & Otimização do MediaPipe (v0.8.2 Alpha)
- **Sub-sistema Modular de Trava de Jogador (`sensor/person_lock.py`):**
  - **Inertial Coasting Filter (`InertialCoastingFilter`):** Mantém a trajetória e continuidade do esqueleto mesmo durante giros 360°, movimentos ultrarrápidos ou oclusões transitórias de até 250 ms através de extrapolação inercial 3D/2D com amortecimento exponencial ($0.88^k$) e transição suave LERP (3 frames) ao recuperar a detecção.
  - **Dancer Identity Lock (`DancerIdentityLock`):** Gera uma assinatura cromática HSV (12x8 bins) do tronco do dançarino e calcula a correlação de Bhattacharyya/Intersecção ($H > 0.35$), garantindo que a câmera nunca troque de jogador mesmo se outra pessoa cruzar o campo de visão.
  - **Atenuação Periférica de ROI:** Prioriza dinamicamente o dançarino ativo diminuindo a sensibilidade de bordas para ignorar pessoas ao fundo ou nas laterais.
  - **Arquitetura 100% Modular e Desacoplada (`PersonLockController`):** Pode ser ativado ou desativado de forma transparente e flexível via `config.json` sem impacto de CPU.
- **Smart PTZ Auto-Framing & Face Follow com Fallback 360° (`sensor/pose_filters.py`):**
  - Quando a face é perdida em piruetas ou giros de costas, o algoritmo automaticamente faz fallback para o centroide anatômico da cabeça (`head_center` derivado de ombros, orelhas e nariz), prevenindo saltos abruptos de enquadramento.
  - Zoom dinâmico proporcional à escala do corpo para enquadramento perfeito em qualquer distância.
- **Remoção do Modelo Heavy e Otimização do Bundle:**
  - O modelo `pose_landmarker_heavy.task` (~30.6 MB) e referências foram completamente removidos da base de código e da interface.
  - A interface gráfica agora apresenta de forma limpa e direta apenas os modos **Balanced** (Full) e **Competitive** (Lite), com migração automática e segura de perfis legados.
- **Stereo Vision 60 FPS Boost:**
  - Extração de luminância direta monocromática no leitor nativo da PS4 Camera (`read_left_mono()`) e retificação identidade instantânea (<0.001 ms), liberando ciclos de CPU preciosos.

### 33. Phone Camera via Wi-Fi WebApp & Código QR (v0.8.5 Alpha)
- **Aba de Captura no Sidebar:**
  - Posicionada logo abaixo do **DualShock 4** na barra lateral de navegação (Ordem: PlayStation®Camera -> Standard Webcam -> DualShock 4 -> Phone Camera).
  - Ícone vetorial nítido renderizado a partir de `assets/icons/phone.svg` via `render_svg_icon_pil` com supersampling 4x (`#FFFFFF` ativo e `#00439C` inativo) e fallback procedural caso o SVG não esteja disponível.
- **Conexão Sem Instalação via QR Code:**
  - Exibe um Código QR gerado internamente (`QRCodeGenerator` ISO/IEC 18004 puro em Python) apontando para servidor HTTPS local com certificado autoassinado X.509 ASN.1 DER (`SelfSignedTLSManager`).
  - Funciona em qualquer navegador moderno Android (Chrome) ou iOS (Safari) sem necessidade de instalar aplicativos ou arquivos APK/IPK.
  - **Controles no Navegador Mobile:**
    - Botões dedicados lado a lado para seleção direta de câmera: **Front Camera** e **Rear Camera** (com destaque visual `primary` azul para a lente atualmente ativa).
    - Botão **Cool Mode** (substituindo o antigo *Dim Screen*) posicionado abaixo das duas opções de câmera, ativado por padrão no Android com Auto-Dim em 15s e economia térmica de rede/GPU mantendo o stream WebSocket ativo.
  - **Segurança de Pareamento & Anti-Reconexão Fantasma:**
    - Token criptográfico por sessão (`?t=<token>`) embutido no QR Code e rotacionado automaticamente a cada inicialização, clique em **Disconnect** ou atualização do QR Code (`↻`). Links antigos ou pré-carregamentos em segundo plano do Safari recebem `403 Forbidden` (sem ligar a câmera).
    - Handlers `pagehide`, `beforeunload` e `visibilitychange` encerram imediatamente as faixas da câmera e o WebSocket ao fechar a aba ou trocar de aplicativo no iOS/Android.
  - **Otimização Térmica (Modo Standby & Downscaling Automático):**
    - Enquanto o rastreamento no PC não está ativo, o celular opera em **Standby (Cool Mode)** com heartbeat leve (zero compressão JPEG ou envio contínuo de vídeo).
    - Durante o rastreamento, o canvas reduz automaticamente a resolução nativa do sensor (ex: 1080p no iPhone) para o preset configurado (`640x480`), utilizando qualidade JPEG `0.55`, loop auto-regulado (`setTimeout`) e limite de FPS no ISP (`max: targetFps`) para evitar superaquecimento em aparelhos mais antigos como iPhone 7.
- **Visibilidade de Estado na Interface:**
  - Quando desconectado: o QR Code e instruções de pareamento ocupam a visualização.
  - Quando conectado: o QR Code se oculta, revelando status do smartphone, botão **Disconnect**, resolução, FPS e opções de exibição (a seleção da lente é feita diretamente no smartphone).
- **Arquitetura Híbrida Preparada para Edge Computing:**
  - Transmissão de vídeo via WebSocket binário JPEG em modo `pc_video` (inferência no PC) e contrato estruturado para recepção de métricas diretas no modo `phone_edge`.

### 34. Suporte a 2 Jogadores (2P Duo), Memória Anti-Swap para Valsas/Cruzamentos & Lite AI Padrão (v0.9.0 Alpha)
- **Motor Multi-Jogador Desacoplado (`sensor/player_slot.py`, `sensor/player_reid.py` & `sensor/pose_tracker.py`):**
  - Suporta nativamente **1 Jogador (Solo)** e **2 Jogadores (Duo)**.
  - **Detecção 2P (`num_poses=3`) com Filtro Anatômico Unificado (`is_plausible_human_dancer`) & Pose NMS:** Em modo 2P, o detector MediaPipe opera com `num_poses=3` para propor candidatos extras sem sobrecarregar a CPU. Cada candidato passa pela validação anatômica e pela supressão de duplicatas (`suppress_duplicate_poses`) antes da atribuição de slots, rejeitando móveis ou propostas duplicadas.
  - **Resolução de Inferência 640px (`INFER_MAX_W_2P = 640`):** Buffer de inferência em 640px de largura (ganho de 78% em densidade de amostragem em relação a 480px), mantendo braços e pernas nítidos a até 3 metros da câmera sem sobrecarregar a CPU.
  - Cada jogador possui sua própria instância isolada `PlayerSlotState` (`HandAnchorFilter`, `AdaptiveSmoother`, `SkeletonCalibrator`, `CameraSpaceXTracker`, `PersonLockController`, suavização temporal de segmentação `_seg_prob_ema` e `LongTermIdentityProfile`).
- **Memória de Identidade Anti-Swap (`LongTermIdentityProfile` & `MultiPlayerAssociator`):**
  - Resolve o problema histórico do Kinect de inverter Jogador 1 e Jogador 2 durante valsas, abraços ou cruzamentos rápidos:
    1. **Assinatura Visual Multi-Região Avançada (`AppearanceSignature`):** Combina histograma HSV 16x8 da camisa/torso (35%), perfil de luminosidade V da camisa (20%), histograma HSV 12x6 da calça/pernas (15%), perfil de luminosidade V da calça (10%), razão de contraste de brilho tronco/pernas (10%) e proporção relativa de altura corporal (10%). Permite discriminar dançarinos com precisão mesmo quando ambos vestem roupas escuras ou neutras.
    2. **Memória Âncora Permanente (`anchor_sig`) vs. Assinatura Viva (`live_sig`):** Consolida a identidade nos primeiros 25 quadros limpos e separados e mantém a âncora protegida durante toda a música (resetável com `[C] Recalibrate`).
    3. **Guarda de Proximidade / Valsa (`is_crowded`) & Trava de Aglomeração:** Congela instantaneamente o aprendizado de cor quando as caixas delimitadoras se aproximam (`dist < 0.22` ou `IoU > 0.08`), impedindo contaminação da memória. Trava trocas impulsivas de slot enquanto os dançarinos permanecerem sobrepostos.
    4. **Inércia Espacial de Slot (`CURRENT_SLOT_INERTIA_BONUS = 0.22`) & Momentum Cinemático Direcional:** Aplica desconto de custo para preservar a continuidade espacial do slot anterior e calcula o alinhamento vetorial da velocidade $(\vec{v} \cdot \vec{d})$, guiando os dançarinos com segurança através de cruzamentos em alta velocidade.
    5. **Auditoria Re-ID Pós-Separação:** Quando os dançarinos se separam novamente após um cruzamento, audita os dois slots contra suas `anchor_sig` permanentes e desfaz automaticamente qualquer inversão de slot.
    6. **Memória de Reentrada (até 15s):** Se um jogador sair temporariamente do quadro e voltar pelo lado oposto, reassume automaticamente seu slot original.
- **Composição de Máscara Indexada (`compose_player_index_mask` & `JMI2`) e Singleton `get_kinect_bridge()`:**
  - Compõe a matriz `320x240 uint8` com `0` = Fundo, `1` = Jogador 1 e `2` = Jogador 2, resolvendo pixels sobrepostos pela menor profundidade $Z$ (`center_z`).
  - Grava simultaneamente os 2 esqueletos em `Local\LegacyWebcamKinectPoseV2` (`JDP2`, 664 bytes, `tracked_mask` bits 0 e 1) e a máscara indexada em `Local\LegacyWebcamKinectImageV2` (`JMI2`), mantendo `JDP1` e `JMI1` (`255`) ativos para retrocompatibilidade.
  - `get_kinect_bridge()` unifica a ponte IPC em instância singleton em todo o processo.
- **Paleta Visual P1 Azul / P2 Laranja Claro & Gesto `[ENTER]` Dual:**
  - **Jogador 1 (P1):** Silhueta, contorno, esqueleto e badge `P1` em **Azul** (`BGR 255, 150, 30`).
  - **Jogador 2 (P2):** Silhueta, contorno, esqueleto e badge `P2` em **Laranja Claro** (`BGR 95, 185, 255`).
  - Qualquer um dos jogadores (P1 ou P2) pode erguer o braço por 2 segundos para disparar `[ENTER]`.
- **Lite AI como Padrão na Interface & Aviso Automático em 2P:**
  - O perfil **Competitive (Lite AI)** passa a ser o padrão recomendado (`RECOMMENDED`) da interface para garantir máxima fluidez em 1P e 2P.
  - Quando **2 Players [Experimental]** é selecionado na aba **Tracking**, um banner de aviso logo abaixo da seleção de modelo orienta que o **Lite AI** é o modelo ideal para sustentar FPS estável na CPU com 2 jogadores.

### 35. Modernização Visual do HUD & Efeitos Gamificados de Rastreamento (v0.9.1 Alpha)
- **Cápsulas Flutuantes Estilo Glass Pills (`draw_rounded_glass_pill`):**
  - Substituição das antigas barras pretas horizontais opacas que cortavam o topo e a base da tela por cápsulas flutuantes com cantos arredondados, fundo de vidro escuro translúcido (`alpha=0.62`) e bordas sutis neon/azuladas.
  - **Distribuição Anatômica Inteligente:**
    - **Pílula Superior Esquerda:** Branding da aplicação ("LEGACY PSCAM") e modelo/resolução da câmera.
    - **Pílula Superior Direita:** Métricas em tempo real de FPS da câmera, FPS do pipeline de tracking e integridade da ponte IPC (`Kinect JDP1/JMI1`).
    - **Pílula Lateral Direita (Abaixo de FPS):** Status do dançarino (`DANCER ACTIVE` / `SEARCHING DANCER...`), nível de calibração (`FULL BODY` / `HALF BODY`) e indicador de slots ativos (`P1` em Azul e `P2` em Laranja Claro), empilhado verticalmente logo abaixo do bloco de FPS para eliminar qualquer compressão horizontal em resoluções 4:3 (como 640x480) e manter o centro superior 100% livre.
    - **Pílula Inferior Central:** Badges compactos dos atalhos de teclado (`[C] Calibrar • [H] HUD • [P] PiP • [Q/ESC] Sair`), liberando completamente os cantos inferiores da tela para que os pés dos dançarinos fiquem 100% visíveis em corpo inteiro.
- **Modo Picture-in-Picture Always-On-Top (`[P]`):**
  - Ao pressionar `P` na janela de tracking, a janela redimensiona automaticamente para uma minijanela compacta (`320x240` em 4:3 ou `320x200` em 16:10) que permanece sempre no topo (`HWND_TOPMOST`) acima do Just Dance PC.
  - Exibe apenas a imagem normal da câmera junto com a silhueta neural fiel do jogador e as linhas do esqueleto, ocultando todas as pílulas e textos informativos do HUD. Pressionar `P` novamente restaura o tamanho normal e desativa o `Always-On-Top`.
- **Ciclo de Modos de HUD (`[H]`):**
  - **Modo 0 (Full HUD):** Exibe todas as métricas detalhadas (câmera, FPS, IPC, status e atalhos).
  - **Modo 1 (Minimalist / Clean Dance):** Exibe apenas a pílula de status no canto superior direito, reduzindo distrações na tela.
  - **Modo 2 (Off / Immersive Mirror):** Desativa completamente todo o HUD textual, mantendo apenas a silhueta do jogador e o esqueleto anatômico para uma experiência de espelho de dança totalmente imersiva.
- **Anel de Progresso Radial de Gesto (`draw_gesture_feedback`):**
  - Ao erguer a mão por 1.5–2.0 segundos para disparar o comando de `[ENTER]`, um anel radial de progresso neon (`cv2.ellipse` de 0° a 360°) renderiza diretamente ao redor da mão erguida do jogador, acompanhando seu movimento em tempo real.
  - Inclui ponto luminoso orbitante indicador de progresso e, ao atingir 100%, emite ondas concêntricas expansivas verdes com aviso luminoso `ENTER SENT!`.
- **Aura Dinâmica na Mão de Pontuação (Scoring Hand Aura):**
  - O jogador que utiliza a emulação de celular (Virtual Phone) recebe um halo pulsante e anéis radiantes na mão ativa de pontuação (mão direita ou esquerda configurada).
  - O raio e o brilho do halo reagem dinamicamente à velocidade instantânea do braço (`hand_speed`), oferecendo feedback visual imediato para movimentos rápidos e viradas de dança.
- **Contorno Neon Duplo na Silhueta (`draw_player_silhouette`):**
  - O contorno da silhueta foi aprimorado com uma camada dupla: um glow suave colorido de 3px com interpolação anti-aliasing seguido por uma linha de acabamento interna ultra-nítida de 1px, resultando em um visual moderno com identidade visual limpa.

### 36. Transição Fluida no USB para DualShock 4 & Validação Reativa do Botão Start Tracking (v0.9.2 Alpha)
- **Conexão USB Estável e Transição Imediata da Interface (`DS4Controller` & `DeviceController`):**
  - **Correção de Escopo de Tempo:** Adicionado o módulo padrão `time` em `ui/controllers/device_controller.py`, eliminando a interrupção silenciosa (`NameError`) no cálculo da taxa instantânea em Hz e permitindo que o estado de conexão seja lido de forma contínua e determinística.
  - **Transição Automática de Tela:** Ao plugar o controle via cabo USB, a interface do usuário oculta imediatamente o balão informativo `ds4_disconnected_box` ("Connecting to...") e ativa o quadro de métricas e status `ds4_info_frame`, apresentando em tempo real nível de bateria com indicador de carregamento `[Charging]`, frequência de amostragem em Hz e telemetria tridimensional do acelerômetro (`X`, `Y`, `Z` e magnitude `|G|`).
  - **Prevenção de Re-desconexão Indesejada:** Ajustado o worker `connect_ds4_async` para não forçar ciclo de desconexão e delay caso o dispositivo já se encontre conectado, evitando desconexões instantâneas durante requisições assíncronas concorrentes.
- **Validação Reativa do Botão Principal "Start Tracking" / "Start Controller" (`_update_start_button_state`):**
  - O botão de ação principal da janela (`btn_start`) agora é dinamicamente habilitado (`setEnabled(True)`) apenas quando o hardware ou stream do modo selecionado estiver fisicamente detectado, pareado e pronto para uso:
    - **PlayStation Camera (`pscam`):** Habilitado apenas quando a câmera estiver conectada e o driver WinUSB/DirectShow reportar status `READY`.
    - **Webcam (`webcam`):** Habilitado apenas quando houver pelo menos uma câmera válida detectada e selecionada no sistema.
    - **Phone Camera (`phone_cam`):** Habilitado apenas quando um smartphone estiver ativamente pareado e conectado via WebSocket.
    - **DualShock 4 (`ds4`):** Habilitado apenas quando o controle estiver conectado (`is_connected = True`) via USB ou Bluetooth.
  - **Feedback Visual Aprimorado:** Quando o dispositivo correspondente estiver desconectado, o botão exibe o cursor proibido (`ForbiddenCursor`), o estilo visual desabilitado em cinza suave e tooltips explicativas em tempo real (ex.: *"PlayStation Camera not connected. Connect via USB 3.0 to start tracking"*), impedindo que o usuário tente iniciar uma sessão de rastreamento com dispositivos ausentes.
- **Estabilidade Multithreading e Prevenção de Concorrência DirectShow (`_CAMERA_HW_LOCK`):**
  - **Serialização de Hardware:** Introduzida a trava global reentrante `_CAMERA_HW_LOCK` em `sensor/camera_manager.py` para isolar todas as aberturas e liberações de `cv2.VideoCapture(CAP_DSHOW)` e evitar corrupção de heap do Windows (`0xc0000374`).
  - **Sincronização Atômica de Warmup:** O `CameraController` agora rastreia formalmente o ciclo de vida da thread de pré-aquecimento (`self._warmup_thread`), garantindo que alternâncias rápidas entre modos (ex.: DualShock 4 -> Webcam -> Start Tracking) aguardem deterministicamente o encerramento da thread anterior antes de iniciar a sessão de rastreamento.
  - **Correção de Tipos Win32 em `FindFirstFileW`:** Definidos explicitamente `restype = wintypes.HANDLE` e `argtypes` em `sensor/ps4_backend/driver_installer.py`, evitando truncamento de ponteiros de 64 bits em `c_long` e violações de acesso (`0xc0000005`) durante inspeções de pacotes de driver INF.

### 37. Unificação Visual da UI de Tracking do Controle com a Webcam (v0.9.3 Alpha)
- **Design Unificado de Floating Glass Pills (Estilo PlayStation & Just Dance):**
  - **Identidade Visual Compartilhada:** A interface da janela de rastreamento do controle (`run_ds4_tracking_session`) foi completamente remodelada para utilizar a mesma arquitetura de design visual da webcam (`TrackingOverlay`), com cantos arredondados, fundo de vidro semi-transparente obsidiana (`COLOR_GLASS_BG`) e bordas foscas suaves (`COLOR_GLASS_BORDER`).
  - **Top-Left Pill (Branding & Perfil):** Exibe a marca d'água "LEGACY PSCAM SENSOR", o orbe de destaque em azul PlayStation e as informações do periférico (nome do controle, tipo de conexão USB/Bluetooth e mão ativa configurada).
  - **Top-Right Pill (Telemetria & Polling):** Telemetria em tempo real com indicador de status, frequência de leitura em Hz, porcentagem de bateria com ícone de carregamento e estado da conexão com o Celular Virtual (Just Dance PC).
  - **Right Pill (Status de Rastreamento):** Posicionado diretamente abaixo da pílula de telemetria (exatamente como na webcam), exibindo status dinâmico `"CONTROLLER ACTIVE"` (com ponto pulsante em verde esmeralda), `"SEARCHING CONTROLLER..."` (âmbar suave com prompt de reconexão) ou `"SENSOR IMU FROZEN"` (laranja de aviso para conexões Bluetooth com bloqueio de acelerômetro).
  - **Center Stage — Motion Force Estável & Telemetria do Giroscópio/Acelerômetro:**
    - **Círculo de Motion Force Estável:** Círculo em vidro obsidiana fosco limpo, sem efeitos de pulso senoidal ou animações distrativas, com leitura nítida e direta da aceleração total em $|G|$.
    - **Cartão de Telemetria do Giroscópio & Acelerômetro:** Introduzido um elegante cartão de vidro translúcido contendo 3 barras horizontais bi-direcionais estilizadas com trilha recuada, marcador central de 0G e leitura numérica formatada:
      - **Eixo X (Lateral / Roll):** Gradiente em Ciano Elétrico (`#1EE1F5`).
      - **Eixo Y (Vertical / Pitch):** Gradiente em Âmbar Suave (`#FFC33C`).
      - **Eixo Z (Forward / Depth):** Gradiente em Verde Esmeralda (`#50DC6E`).
  - **Pílula de Seleção de Coach Acoplada:** A pílula de seleção de dançarino (`COACH 1 OF 4`, `[L1]` e `[R1]`) foi posicionada **exatamente acima da barra de comandos de teclado**, com indicação do nome da música ativa e alinhamento ergonômico.
  - **Bottom-Center Pill (Barra de Atalhos):** Pílula centralizada com atalhos de teclado limpos `[Q/ESC] Exit • [R] Reconnect • [L1/R1] Coach • [H] Cycle HUD`.
  - **Suporte a Ciclo de HUD (`[H]`):** Alternância entre HUD Completo (0), Minimalista (1) e Desativado (2) através da tecla `[H]`.

### 38. Resiliência de Câmera Frontal no Smartphone e Fallback em Escada (v0.9.4 Alpha)
- **Cascata Progressiva de Restrições (`startCamera()`):**
  - **Eliminação de `OverconstrainedError`:** Removida a restrição rígida de taxa de quadros máxima (`max: 30`), substituída por preferência ideal (`ideal: targetFps`), permitindo que sensores de câmera frontal com taxas variáveis ou limitadas pelo driver sejam aceitos sem rejeição pelo navegador.
  - **Identificação Exata por Dispositivo (`enumerateDevices`):** Implementada busca antecipada por `deviceId` através de enumeração de dispositivos de hardware, mapeando sensores frontais (`front`, `selfie`, `face`, `anterior`, `frontal`) e traseiros (`back`, `rear`, `environment`, `traseir`) com fallback progressivo até o modo mais permissivo.
  - **Tratamento de Liberação de Hardware:** Inserido intervalo de liberação de 160ms após parada de trilhas de mídia para permitir que o daemon do Android Camera2 / iOS AVFoundation finalize a sessão antes de abrir o novo sensor, prevenindo `NotReadableError` e `TrackStartError`.
  - **Diagnóstico Preciso de Erros:** Tratamento diferenciado para erros de câmera na interface web mobile (`NotAllowedError` para permissão, `NotReadableError` para hardware ocupado por outros apps, `OverconstrainedError` para limitações de lente e `NotFoundError`), eliminando mensagens falsas de "Camera Permission Denied" quando a permissão já foi concedida.

### 39. Ações Contextuais e Ocultamento Reativo Universal do Botão "Start Tracking" (v0.9.5 Alpha)
- **Ocultação Reativa Universal do Botão "Start Tracking":**
  - Em **todas as abas** (Phone Camera, DualShock 4, PlayStation®Camera e Standard Webcam), enquanto o dispositivo selecionado estiver desconectado ou indisponível, o botão principal `Start Tracking` permanece **completamente oculto** ao invés de ficar cinza/desabilitado, mantendo a área de ações inferior totalmente limpa até que o hardware correspondente seja detectado e fique pronto.
- **Botão "Disconnect" Vermelho ao Lado do Start Tracking (Phone Camera):**
  - Quando um smartphone se conecta com sucesso, o botão `Start Tracking` surge habilitado acompanhado pelo botão **Disconnect** estilizado em vermelho destrutivo (`#DC2626` / `#B91C1C`) posicionado diretamente ao seu lado na barra inferior de ações.
- **Card de Smartphone Conectado Reestruturado:**
  - O bloco `CONNECTED SMARTPHONE` foi elevado diretamente para o topo do card de configurações de vídeo.
  - O antigo subtítulo estático genérico foi substituído pelo indicador dinâmico de status em verde (ex: `iPhone (iOS Safari) connected (192.168.1.42 • 640x480 @ 30 FPS • Rear Camera)`), unificando os dados do aparelho em um único componente coeso.
- **Limpeza do Cabeçalho Superior:**
  - O antigo botão secundário de desconexão localizado no quadro de metadados superior foi removido, tornando o card de status do dispositivo conectado mais enxuto e organizado.

### 40. Silhueta Neural Fiel, Resiliência a Agachamentos, PiP (`[P]`) & Stereo Vision Padrão (v0.10.0 Alpha)
- **Silhueta Neural Fiel ao Jogador:**
  - Restaurada a máscara de segmentação neural com contorno nítido e preservação de vazios internos naturais (entre braços, pernas e tronco), oferecendo visual idêntico ao corpo real do dançarino tanto na prévia quanto no HUD do Just Dance.
- **Modo Picture-in-Picture Always-On-Top (`[P]`):**
  - Pressionar `P` na janela de rastreamento alterna para uma janela compacta sempre no topo (`HWND_TOPMOST`) para acompanhar sobre o Just Dance exibindo apenas vídeo, silhueta e esqueleto (sem HUD textual).
- **Resiliência Total a Agachamentos Profundos (`is_plausible_human_dancer` & `DancerIdentityLock`):**
  - Ajustados os critérios anatômicos de proporção (`aspect >= 0.28`, checagem em pixels reais) e amortecimento anisotrópico vertical (`dy * 0.38`) na trava de identidade, impedindo perda de tracking durante agachamentos rápidos em coreografias intensas.
- **Stereo Vision Ativado por Padrão na PS4 Camera:**
  - O motor estéreo sub-pixel (`PyrLK`, < 0.5 ms) foi promovido a comportamento padrão automático da PlayStation 4 Camera e removido como checkbox manual da UI, agora com suporte simétrico tanto ao **Olho Direito** quanto ao **Olho Esquerdo** selecionado como lente principal.
  - **Estabilização Anti-Zoom em `Head.z` & Mediana de Tronco:** O aterramento estéreo utiliza mediana robusta dos joints do tronco (`s_conf >= 0.55`, piso NCC `>= 0.50`), limitador físico de velocidade (`±0.035m/frame`), clamping anatômico de braços (`±0.55m`) e EMA permanente em `Head(3)`, eliminando qualquer oscilação de *zoom in / zoom out* no enquadramento facial do Just Dance com Auto-Frame ativo.
- **Refinamentos de UI:**
  - Rodapé inferior direito simplificado para exibir exclusivamente a versão e o estágio (`v0.10.0 (Alpha)`).
  - Opção de 2 jogadores claramente identificada como **`2 Players [Experimental]`** na aba **Tracking**.
- **Inicialização Acelerada, Cache de Modelos em `%APPDATA%` & Builds Duplos (`--onefile` / `--onedir`):**
  - **Gerenciador Persistente de Modelos (`sensor/model_manager.py`):** Mantém o modelo `Lite` (`5.5 MB`) embutido para uso 100% offline e baixa o modelo `Full` (`9.0 MB`) sob demanda apenas quando o usuário escolhe o perfil **Balanced**, salvando atomicamente (`.part → .task` com validação SHA-256) em `%APPDATA%\LegacyPSCam_Sensor\models\` sem travar a interface Qt 6.
  - **Poda Cirúrgica de Binários Mortos (`legacy_pscam_sensor.spec`):** Remove `~92 MB` de DLLs/módulos não utilizados (`opencv_videoio_ffmpeg`, `opengl32sw.dll`, `Qt6Quick`/`Qt6Qml`/`Qt6Pdf`/`Qt6OpenGL`/`Qt6Network`, `PIL._avif`, `_sounddevice_data`), somando `~101 MB` a menos extraídos na abertura.
  - **Splash Screen Instantâneo (`assets/icons/splash.png`):** Exibe tela minimalista Crisp White + PlayStation Blue (`"Hold on... and warm up!"` em DM Sans) em `< 0.3s` no `--onefile`, encerrada automaticamente via `pyi_splash.close()` ao pintar a janela principal.
  - **Identidade Nativa & Release Duplo:** Processo e executável unificados como `LegacyPSCam.exe` com ícone próprio multi-resolução (`app_icon.ico`, barra de tarefas e janelas OpenCV), além de publicação paralela da versão `--onedir` (`LegacyPSCam-Portable-Windows.zip`, abertura `< 1s`) no GitHub Releases.

### 41. Reestruturação de UI: Scoring Bridge no DualShock 4 e Aba Experimental Limpa (v0.10.1 Alpha)
- **Scoring Bridge (Just Dance Controller App mode):**
  - A interface de Celular Virtual foi migrada da aba Experimental para a aba **DualShock 4 (Controller Settings)**, consolidada em uma nova pílula visual dedicada.
  - O componente exibe estritamente os 4 controles essenciais para a ponte de pontuação com o Just Dance:
    1. **Status de Conexão com o Jogo:** Indicador em tempo real (Desconectado, Conectando ou Conectado ao servidor WebSocket local).
    2. **Botão "Reconnect Game":** Reconexão rápida ao servidor do jogo (`127.0.0.1:8080`).
    3. **Botão "Auto-Find":** Busca automática por broadcast UDP para localizar instâncias do Just Dance na rede.
    4. **Botão "Skip Finish":** Atalho para contornar a tela de introdução do tutorial de celular no Just Dance 2022, transferido para dentro da pílula.
  - A descrição original detalhada do Virtual Phone foi preservada no cabeçalho da pílula.
- **Limpeza do Bloco Controller Hardware:**
  - O botão `Skip Finish` foi removido da linha de ações do hardware (`Controller Hardware`), mantendo aquela área focada exclusivamente nas ações físicas do gamepad (`Test Rumble Vibration` e `Reconnect Controller`).
- **Aba Experimental Contextual por Modo:**
  - Nos modos de câmera (**PlayStation 4 Camera**, **Standard Webcam** e **Phone Camera**), a aba `Experimental` preserva integralmente o aviso de cautela, o **Auto-Frame (Digital PTZ)** e o **Virtual Phone Controller (JD Controller via Camera)**.
  - No modo **DualShock 4**, a aba `Experimental` fica limpa como placeholder (`"No experimental features available at this time."`), já que os controles da ponte de pontuação vivem na pílula dedicada **Scoring Bridge** dentro de `Controller Settings`.
- **Otimização de Alto FPS para Android no Phone Camera WebApp (`assets/webapp/mobile_webapp.html` & `sensor/phone_camera.py`):**
  - Substituída a verificação estrita `ws.bufferedAmount > 0` (que causava travamentos e descarte de frames devido ao IPC assíncrono do Chrome no Android) por uma janela de backpressure de `128 KB`, permitindo 1–2 frames em voo sem engasgar o fluxo Wi-Fi.
  - Adotado `video.requestVideoFrameCallback` (sincronizado diretamente aos frames de hardware da câmera, eliminando o *sleep* forçado de `10ms` por frame).
  - Adicionado controle adaptativo de qualidade JPEG (`0.38`–`0.55`), limites máximos nas constraints `getUserMedia` para impedir captura em 1080p/4K em drivers Android Camera2, remoção de `backdrop-filter: blur` sobre o `<video>` (que quebrava hardware overlay em GPUs Mali) e unmasking XOR in-place sem cópias extras no servidor Python.
  - **Notificação Reativa de Orientação Horizontal (`Rotate your phone horizontally`):** Pílula de aviso com ícone vetorial de rotação (vertical → horizontal) exibida automaticamente acima da barra de controles tanto na janela de rastreamento do PC (`sensor/tracking_overlay.py`) quanto no WebApp móvel (`assets/webapp/mobile_webapp.html`) sempre que o celular estiver na vertical, ocultando-se instantaneamente assim que o aparelho for virado para paisagem.
  - **Resiliência de Conexão Wi-Fi / Anti-`ERR_CONNECTION_TIMED_OUT` (`sensor/phone_camera.py`, `sensor/tls_manager.py`, `ui/pages.py`, `ui/gui_qt.py`):**
    - Enumeração nativa Win32 (`iphlpapi.GetAdaptersAddresses`) que prioriza adaptadores físicos Wi-Fi/Ethernet (`192.168.x.x` / `10.x.x.x`) acima de túneis VPN e interfaces virtuais (Radmin VPN, Tailscale, Hamachi, WireGuard, OpenVPN, WSL, Hyper-V, VirtualBox, VMware).
    - Certificado TLS X.509v3 com **multi-IP SubjectAltName (SAN)** abrangendo todos os IPs locais detectados, combinado com seletor manual de adaptador/IP diretamente no card do QR Code.
    - Diagnóstico instantâneo de regras do Windows Defender Firewall via Registry (`winreg`, sem admin) e botão **`Allow Firewall`** com elevação UAC sob demanda para liberar a porta TCP do Phone Camera em redes **Private e Public**, resolvendo bloqueios silenciosos que causavam `ERR_CONNECTION_TIMED_OUT`.
    - Timeout inicial do handshake ampliado (`3s → 10s`), log estruturado de erros de conexão no `session.log` e correção do readout de lente/resolução/FPS no `DeviceController`.
- **Blindagem do Emulador Kinect para Windows 10 (`sensor/kinect_emulator.py` & `sensor/tracking_session.py`):**
  - Enumeração estrita de módulos 32-bit (`LIST_MODULES_32BIT = 0x01` + validação de espaço de endereço `< 4 GB` e magic `PE32 0x010B`), eliminando falhas silenciosas de `NO_LOADLIB` quando módulos WoW64 64-bit aparecem na enumeração do Windows 10.
  - Staging automático de `Legacy10.dll` para `%APPDATA%\LegacyPSCam_Sensor\tools\` em builds `--onefile`, evitando bloqueios do Windows Defender ao carregar DLLs de `%TEMP%\_MEI*`.
  - Leitura dinâmica da tabela `OriginalFirstThunk` (ILT) por ordinal e nome, checagem de `GetExitCodeThread` do `LoadLibraryW`, polling mais rápido (`100ms`) para capturar o boot do jogo, suporte a aliases (`JustDance2017.exe`, `LegacyOffline.exe`) e feedback visual de diagnóstico no HUD (`GAME: Run as Administrator!`, `GAME: Check Antivirus/AV!`, `IPC: Active • Game Linked`).
  - Proteção no modo câmera para que um flag residual `virtual_phone_enabled` do modo DualShock 4 nunca zere o esqueleto Kinect na memória compartilhada.
- **Correção de Crash Imediato e Blindagem de Sobreposição no Modo 2 Players (`sensor/player_slot.py`, `sensor/pose_tracker.py`, `sensor/person_lock.py` & `sensor/tracking_session.py`):**
  - Corrigido `UnboundLocalError` em `extract_detection_features()` (`lower_v_hist`, `body_height` e `contrast_ratio` não inicializados quando os joelhos do jogador estavam fora do enquadramento), que fazia a janela de rastreamento 2P abrir e fechar imediatamente no primeiro frame.
  - **Pose NMS Anti-Duplicatas (`suppress_duplicate_poses`):** Suprime propostas sobrepostas geradas pelo MediaPipe sobre o mesmo corpo durante contato físico (ex.: braço de P1 sobre P2) usando geometria de tronco e mediana dos landmarks centrais, impedindo que uma duplicata de P2 roube o slot de P1.
  - **Associação Multi-Candidatos e Inércia Espacial Real (`MultiPlayerAssociator`):** Avalia todos os candidatos pós-NMS contra a memória persistente de P1 e P2 (eliminando o corte cego `[:2]`) e substitui a inércia por índice de array (que induzia trocas quando a ordem de pontuação mudava) por continuidade espacial predita.
  - **Resiliência a Oclusão Parcial de Ombro e Coasting Estendido de Sobreposição (`650 ms`):** Permite oclusão momentânea de um ombro sem rejeitar o dançarino (`is_plausible_human_dancer` / `extract_detection_features`), preserva o estado `is_crowded` mesmo quando apenas 1 detecção sobrevive ao contato (congelando a assinatura visual contra contaminação) e estende o coasting inercial para até `650 ms` com amortecimento reforçado (`0.65`) durante sobreposições.
  - **Isolamento Anti-Engolimento de Silhueta 2P (`_build_exact_player_mask`):** Quando braços se tocam e a segmentação neural funde ambos os corpos em um único componente conexo, recorta os pixels exclusivos do envelope anatômico do outro jogador, além de eliminar o fallback indevido para `seg_list[0]` de outro jogador.
  - **Otimização de CPU e Telemetria Diagnóstica 2P:** Ajuste de `num_poses = 3` com limiares 2P otimizados para oclusão (reduzindo ~25% do pico de inferência CPU em relação a 4 poses) e logs estruturados com throttling (`TRACKING_2P`: `2p_nms_dup`, `2p_crowd_coast`, `2p_swap_audit`, `2p_drop`) e traceback completo em `session.log`.
- **Estabilização 1P, Anti-Throttling Windows 11 EcoQoS & Silhueta Completa no Just Dance Legacy (`sensor/tracking_session.py`, `sensor/person_lock.py`, `sensor/player_slot.py`, `sensor/pose_tracker.py` & `sensor/tracking_overlay.py`):**
  - **Proteção Contra EcoQoS / Throttling em Segundo Plano no Windows 11 (`set_realtime_process_qos`):** Ativa `HIGH_PRIORITY_CLASS` e desativa explicitamente `ProcessPowerThrottling` (`SetProcessInformation`, `ControlMask=1, StateMask=0`) + `SetThreadExecutionState` durante sessões ativas de rastreamento, impedindo que o Thread Director do Windows 11 rebaixe o sensor para E-cores (~13 FPS) quando o `Legacy.exe` assume a tela cheia — preservando taxa de inferência acima dos 30 FPS do Kinect e pontuação estável no jogo.
  - **Silhueta Neural Completa Sem Cortes (`_build_exact_player_mask`):** Limiar neural calibrado em `0.36` (evitando cortes em cabelo/topo da cabeça e pernas/pés escuros no modelo Lite sem preencher os vãos entre braços e cintura) aliado à recuperação cirúrgica de bordas superior/inferior quando a caixa ROI quadrada interna do MediaPipe corta extremidades visíveis, mantendo preenchimento total de `640x480` / `320x240` sem faixas pretas artificiais e vídeo ao vivo contínuo no IPC.
  - **Resiliência a Giros 360° e Enquadramento Inicial de Menu:**
    - `is_plausible_human_dancer()` aceita perfis laterais de 90° em giros (`sh_w` estreito com corpo alto `bbox_h >= 0.24`) e enquadramento inicial de tronco superior (cabeça + ombros nítidos, `score >= 2.2`), além de registrar o motivo exato de qualquer rejeição em `session.log` (`explain_plausibility_rejection`).
    - `InertialCoastingFilter` utiliza amortecimento exponencial normalizado ao `dt` real (`250 ms` padrão, piso conservador de `320 ms` sob picos de CPU para nunca enviar poses congeladas longas ao avaliador rítmico do Just Dance).
    - `PersonLockController.apply_pre_inference_roi()` desativa automaticamente o escurecimento periférico durante coasting para que o MediaPipe enxergue o quadro inteiro na reaquisição, e `DancerIdentityLock` adapta o raio de salto ao `dt` e libera travas obsoletas em até 18 frames.
  - **Preview Otimizado Sob Gameplay em Tela Cheia:** `draw_player_silhouette()` otimizado com blur pré-upscale, `CHAIN_APPROX_SIMPLE` e `cv2.copyTo` SIMD, buffer de prévia limitado a `800px` de largura e pausa automática da renderização OpenCV quando a janela está minimizada (`IsIconic`).
- **Estabilização Crítica Fase 1 — Rastreamento, Estéreo, Hardware USB/DS4, Emulador e IPC:**
  - **Remoção do Toggle Legado `mirror_horizontal` / `[M]`:** A inferência do MediaPipe permanece sempre no frame bruto não-espelhado, enquanto o preview e o IPC Kinect são sempre espelhados horizontalmente (garantindo alinhamento 1:1 com o esqueleto 3D Kinect e `FaceFollowPTZ` e eliminando o atalho obsoleto `[M] Mirror`).
  - **Precisão Anatômica e 2P 60 FPS (`sensor/player_slot.py`, `sensor/person_lock.py`, `sensor/pose_tracker.py`):** Corrigida a inversão esquerda/direita na síntese de pernas em modo *upper-body* (`hips_visible=False`), preservado o `DancerIdentityLock` em `reset_transient()` para manter o gate anti-impostor de 18 frames ativo, condicionado o recorte *Anti-Swallow* 2P a `is_crowded=True` (economizando até 4 construções de máscara/frame quando jogadores estão separados) e trocado o relógio de timestamp do MediaPipe para `time.perf_counter()` monotônico sem fallback inválido para `world_landmarks`.
  - **Precisão de Visão Estéreo (`sensor/stereo_matcher.py`):** Corrigida a janela epipolar do olho direito (desbloqueando profundidades > 3 m), ativada escala automática de `search_radius_px` por resolução (permitindo medir dançarinos próximos ~0.65–1.0 m em `1280x800`) e corrigido o sinal da translação `T = [-B, 0, 0]` em `cv2.stereoRectify`.
  - **DualShock 4, WinUSB PS4 Camera & Driver/Firmware (`sensor/ds4_controller.py`, `sensor/ps4_backend/`):** Escala IMU (`LSB/G`) travada durante janela inicial de repouso (impedindo que golpes rápidos > 1.46 G cortem a força G pela metade), assinaturas Win32 64-bit completas e fechamento seguro de handle após `join()` da thread HID; drenagem obrigatória de URBs isócronos pós-`CancelIoEx` com validação de limites antes de `memmove` em `frame_streamer.py`; detecção real de `WAIT_TIMEOUT` no `pnputil.exe` (`driver_installer.py`) e serialização por lock no upload de firmware OV580 (`firmware_manager.py`).
  - **Emulador Kinect, FrameBus, IPC e CLI (`sensor/kinect_emulator.py`, `sensor/camera_manager.py`, `sensor/kinect_shared_memory.py`, `sensor/virtual_phone.py`, `main.py`):** Match exato de executáveis no scanner de processos, validação PE32 (`MZ`/`PE\0\0`/`SizeOfImage`) + leitura prévia antes do fallback legado `0x9CD250`, proteção contra UAF de `VirtualFreeEx` em timeout de `LoadLibraryW`, seqlock completo + checagem de limites `VirtualQuery` no `FrameBusReader`, suporte real a `tagname` customizado + `RLock` + recuperação de paridade seqlock no `KinectBridge`, correção de `import re` e `self.accelerometer.hand` em `VirtualPhoneController`, suporte à flag `--portable` e repasse de `--mode`/`--camera` para a GUI em `main.py`.
- **Estabilização Térmica Android, Segurança TLS/WSS, Fluidez Qt 6 & Integridade (Fase 2):**
  - **Correção Anti-Superaquecimento Android no Phone Camera WebApp (`assets/webapp/mobile_webapp.html`):**
    - Removida a flag `willReadFrequently: true` do canvas 2D (restaurando aceleração GPU no Chrome Android e eliminando readback GPU→CPU por frame).
    - Constraints de `getUserMedia` estritas ao preset alvo na 1ª tentativa (negociando VGA `640x480` nativo no Android Camera2 HAL em vez de 720p HD no ISP).
    - **Cool Mode (Eco Thermal)** substituindo o botão `Dim Screen` e ativo por padrão no Android: teto de encode `480x360`, JPEG `0.34–0.44` (~55–65% menos TX Wi-Fi/TLS), **Auto-Dim automático após 15 s de streaming** com redução do `<video>` para `2×2 px` (poupando o compositor SurfaceFlinger) e **Governador Térmico Adaptativo** (`targetFps -> 24 -> 20 -> 15 FPS`) ao detectar lentidão de encode.
    - **Standby Frio com Desligamento Real da Câmera:** Reduz imediatamente o sensor para ~10 FPS ao entrar em Standby e desliga fisicamente o `MediaStream` após 25 s ociosos (exibindo *"Camera Sleeping • Cool Standby"*), reabrindo automaticamente ao iniciar o tracking no PC.
    - Eliminados vazamentos de `MediaStream` em chamadas concorrentes de `startCamera()`, congelamentos de `encodingInProgress`, perda de `WakeLock` ao voltar para a aba e desconexões durante troca de lente (heartbeat inteligente).
  - **Segurança TLS Única por Instalação & `PhoneCameraServer` (`sensor/tls_manager.py`, `sensor/phone_camera.py`):**
    - Removidos primos RSA-2048 estáticos do código-fonte; cada instalação gera sua própria chave RSA-2048 persistida atomicamente em `%APPDATA%\LegacyPSCam_Sensor\tls\device_key.pem`, com certificados de validade dinâmica de 365 dias, `KeyUsage`, `ExtendedKeyUsage (serverAuth)` e `TLSv1.2+`.
    - Adicionados `_ws_send_lock` contra escrita concorrente no `SSLSocket`, semáforo de limite de conexões (8), redirecionamento `301` HTTP→HTTPS em clientes LAN, preservação de bytes pipelined, remontagem RFC 6455 de frames fragmentados e proteção contra JSON malformado.
  - **Fluidez da UI Qt 6 & Concorrência (`ui/controllers/*`, `ui/gui_qt.py`, `ui/device_readout_mixin.py`, `ui/widgets.py`):**
    - Probe HID do DualShock 4, validação pré-tracking (`validate_pre_tracking_async`) e verificação SHA-256 de modelos movidos para fora da thread principal Qt; unificado `DeviceController.is_connecting_ds4` (eliminando deadlock de reconexão); `SessionController.cleanup()` aguarda `TrackingSessionThread.join()`; `CameraController` usa geração de cancelamento `_warmup_gen`; `SlidingStackedWidget` libera animações com `DeleteWhenStopped` e evita dessincronização em cliques rápidos; cache de QSS no timer de 150 ms e mensagens de erro contextuais por modo.
  - **Integridade de Telemetria & Modelos (`sensor/session_logger.py`, `sensor/model_manager.py`):**
    - Telemetria CSV com `csv.writer` (suporte seguro a vírgulas/aspas em nomes de músicas), drenagem sincronizada do batch sem perda de linhas ao parar e restauração dos `excepthook` no `close()`.
    - `ModelManager.download_model()` valida SHA-256 estrito por padrão (`strict_hash=True`), com cache de validação por `(path, mtime_ns, size)`, staging protegido por lock e `User-Agent` sincronizado com `version.py`.
- **Engenharia, Refatoração Modular, CI/CD & Documentação (Fase 3):**
  - **Refatoração Re-ID & Precisão Cinemática (`sensor/player_reid.py`, `sensor/player_slot.py`, `sensor/pose_filters.py`, `sensor/gesture_detector.py`, `sensor/vphone_protocol.py`):**
    - Extração limpa do subsistema de Re-ID, plausibilidade anatômica unificada e Pose NMS para `sensor/player_reid.py` (com 100% de re-exports retrocompatíveis em `player_slot.py` e lazy exports completos em `sensor/__init__.py`).
    - Compensação contínua de `dt` no `AdaptiveSmoother` (`eff_alpha = 1 - (1 - alpha_ref) ** (dt / REF_DT)`) para manter a mesma constante física de suavização em 30, 60 e 120 FPS (3D e 2D).
    - Isolamento de cronômetro 2P no `ArmRaiseGestureDetector` (troca P1→P2 reinicia o hold) + chave `"hand_pos"` consistente em todos os retornos.
    - Hardening do cliente WebSocket UbiArt (`MAX_WS_PAYLOAD_BYTES = 2 MB`, truncamento de `_send_pong` <= 125 B antes do cabeçalho RFC 6455, inclusão de `Legacy.exe` em `find_just_dance_pids` e guarda contra `RegionSize == 0`/overflow em `detect_active_song_from_game_process`).
  - **Polimento Qt 6 (`ui/widgets.py`, `ui/pages.py`):** Componente reutilizável `SettingBlock`, conversão de blocos de texto com `wordWrap` de altura fixa para `setMinimumHeight`, remoção de propriedades CSS `line-height` inválidas no Qt e correção da descrição do bloco **DS4 Scoring Bridge**.
  - **Testes Isolados, Build Reprodutível & CI/CD (`test_suite.py`, `tests/`, `legacy_pscam_sensor.spec`, `.github/workflows/ci.yml`, `release.yml`):** Isolamento hermético de `%APPDATA%` e porta efêmera `0` durante os testes, nova suíte modular `unittest` sob `tests/`, `.spec` independente de `cwd` com splash em `build/splash.png` e poda de `__pycache__`/`licenses/NOTICE`, CI automático em `push`/`PR` e pipeline de release com validação de tag, `STAGE` dinâmico, smoke test dos executáveis e `SHA256SUMS.txt`.
- **Lançamento v0.11.0 — Suporte Nativo 64-bit ao Legacy Lab, Modularização & Polimento UX:**
  - **Compatibilidade 64-bit com Just Dance Legacy Lab (`tools/Legacy10_x64.dll`, `tools/legacy10_x64_src/`, `sensor/kinect_emulator.py`, `sensor/vphone_protocol.py`):** Nova proxy DLL nativa x64 (ABI completa `INuiSensor`/`INuiFrameTexture` do Kinect SDK v1.8, zero dependências externas, pacer 30 FPS e leitura seqlock de `JDP2`/`JDP1`/`JMI2`/`JMI1`/`JXC1`), suporte a injeção 64-bit + patch de **Delay Import Table** + cache `HMODULE` em RAM para `Legacy Lab.exe` (ignorando `legacylab-launcher.exe`), além de suporte em `find_just_dance_pids()`.
  - **Troca de Modo Instantânea (Zero Freeze) & Scoring Bridge DS4 (`ui/mixins/camera_handlers.py`, `ui/controllers/camera_controller.py`, `sensor/camera_capture.py`, `ui/pages/ds4_page.py`):** Cancelamento assíncrono não-bloqueante da webcam em standby (`CameraPrewarmCloser` serializado + evento interrompível `_stop_event`), eliminando travamentos de 1–3s ao alternar `Webcam → DualShock 4` / `Phone Camera`, e `Scoring Bridge` movido para dentro de `ds4_info_frame` (exibido apenas quando um DualShock 4 está conectado).
  - **Modularização de Monolitos (`ui/mixins/`, `ui/pages/`, `sensor/camera_win32.py`, `sensor/framebus_reader.py`, `sensor/camera_capture.py`, `sensor/body_mask.py`):** Quebra limpa de `gui_qt.py`, `pages.py`, `camera_manager.py` e `pose_tracker.py` em módulos coesos com 100% de retrocompatibilidade.
  - **Polimento Visual (`assets/icons/reload.svg`, `ui/icons.py`, `ui/styles.py`):** Ícone vetorial `reload.svg` (4× supersampled, sem recortes) nos botões de atualização e contorno fino (`1px solid #94A3B8`) na caixa fechada dos `QComboBox`.
- **Hotfix v0.11.1 — `SeDebugPrivilege`, Anti-Zumbi PID & Diagnóstico Preciso de `ACCESS_DENIED`:**
  - `KinectEmulatorDaemon` agora habilita automaticamente `SeDebugPrivilege` via `advapi32.AdjustTokenPrivileges` quando executado como Administrador (corrigindo `Error 5` em processos iniciados por launchers/DACLs restritas), filtra PIDs zumbis encerrados (`GetExitCodeProcess != STILL_ACTIVE`) e itera por todos os processos candidatos vivos.
  - Diagnóstico completo de `ACCESS_DENIED` vs `ACCESS_DENIED_ADMIN` (`sensor_admin`, `se_debug`, `target_elevated`, `can_query`, `can_vm_read`) + linha `Privileges:` no cabeçalho do `session.log` e distinção clara no HUD (`GAME: Run as Administrator!` vs `GAME: Blocked by AV/AntiCheat!`).
  - Corrigido falso positivo em `CameraManager.is_legacy_pscam4win_running()` que detectava o próprio `LegacyPSCam.exe` pela substring `"pscam"`.
- **Atualização v0.11.5 — Correção Crítica de Pontuação 64-bit (Legacy Lab / Legacy Lab Offline), Tracking Estabilizado & Nova Aba Quality Presets:**
  - **Paridade ABI 100% em `tools/Legacy10_x64.dll` (`tools/legacy10_x64_src/legacy10_x64.cpp`):** Adicionado `ResetEvent` em `NuiSkeletonGetNextFrame` e `NuiImageStreamGetNextFrame` (corrigindo busy-spin de 100% CPU nas threads Kinect de eventos *manual-reset* do `Legacy Lab.exe` e injeção de frames duplicados a 1 ms que zerava a pontuação), `timeBeginPeriod(1)` no pacer de 33 ms (30 FPS estáveis), `vNormalToGravity = (0, -1, 0, 0)`, `vFloorClipPlane = (0, 1, 0, 0)`, `dwFrameNumber` monotônico por chamada, `liTimeStamp` relativo a partir de `0 ms`, `dwTrackingID`/`dwUserIndex` 1-based (`1, 2`) e profundidade `2200 mm`.
  - **Suporte ao Legacy Lab Offline (`sensor/kinect_emulator.py`, `sensor/vphone_protocol.py`):** Detecção automática e hook 64-bit para `LegacyLab_Offline.exe` (`legacy lab offline.exe`, `legacylaboffline.exe`).
  - **Estabilização Completa de Tracking (`sensor/pose_filters.py`, `sensor/player_reid.py`, `sensor/pose_tracker.py`):**
    - Corrigida persistência de `stereo_baseline_z` em frames sem triangulação estéreo (eliminando teleportes de `±71 cm` em Z) e travado o piso estéreo na zona de lobby do Kinect v1 (`[1.75 m, 3.40 m]`, protegendo `HipCenter` no blend de membros) para reconhecimento instantâneo no lobby.
    - Escala do `SkeletonCalibrator` travada na faixa física humana `[0.82, 1.42]` com ancoragem ao quadril ao vivo (eliminando explosões de altura até `3.7 m`).
    - Amortecedor anti-teleporte de 1 frame no `AdaptiveSmoother` (`> 0.55 m` com quadril parado) + limite lateral no `CameraSpaceXTracker`, reduzindo saltos espúrios de mão de centenas para zero.
    - Calibração do `plausibility gate` para poses de mesa/braços abertos (`min_score 1.75`, `min_aspect 0.22` com tronco confirmado) e giros 360° altos (`2.6`), além de **Adaptive 1P Inference Width** (`640 → 384 → 320px`) considerando o tempo total do ciclo.
  - **Nova Aba Tracking — Quality Presets & Opções Manuais (`ui/pages/tracking_page.py`, `ui/mixins/tracking_handlers.py`, `ui/theme.py`, `ui/icons.py`, `ui/widgets.py`):** Grade 2×2 de presets por hardware (**Performance**, **Balanced [RECOMMENDED]**, **High**, **Custom**) com 4 controles manuais reais (**AI Model**, **Inference Quality** `320p/Auto/640p`, **Silhouette Cutout** `Fast/Accurate` com `output_segmentation_masks=False` no modo Fast, e **Player Lock** `Enabled/Disabled`), troca automática para **Custom** ao editar qualquer opção e uso estrito de ícones SVG existentes (zero emojis).
- **Emulação Nativa de PlayStation Move (ZCM2) via DualShock 4 & Remoção Completa do Virtual Phone:**
  - **DLLs Proxy Nativas In-Process (`tools/LegacyMove.dll` x86 & `tools/LegacyMove_x64.dll` x64, fonte em `tools/legacymove_src/legacymove.cpp`):** Hook in-process nas tabelas IAT de `SETUPAPI.dll`, `HID.DLL` e `KERNEL32.dll` compatível com as 3 builds do Just Dance PC (`Legacy.exe` 32-bit, `Legacy Lab.exe` 64-bit e `LegacyLab_Offline.exe` 64-bit), com passthrough transparente para todos os dispositivos HID reais, thread pacer de 100 Hz overlapped (`ReadFile`) entregando relatórios ZCM2 de 49 bytes (`VID 0x054C / PID 0x0C5E`) e ocultação total quando `active == 0` (modos de câmera).
  - **Ponte IPC Bidirecional (`sensor/psmove_shared_memory.py` — `Local\LegacyPSMoveState`, `PSM1` 128B):** Transporta aceleração 3D, giroscópio 3D (com auto-calibração de zero-bias em repouso no `DS4Controller`), máscara de botões 1:1 (`R2` → Gatilho `T` analógico+digital, `Cross`/`R1` → `Move`/Confirmar, `Circle` → Voltar, `Square`/`Triangle`, `Options` → `Start`, `Share` → `Select`, `PS` → `Menu`) e bateria (Sensor→Jogo), enquanto recebe em tempo real a cor RGB da esfera e intensidade de rumble (`0x06`/`0x02`) enviados pelo jogo (Jogo→Sensor).
  - **Rotação Ergonômica da Pegada Vertical ("Joinha"):** Transformação ortogonal própria ($\det = +1$) `(move_x, move_y, move_z) = (+ds4_x, -ds4_z, +ds4_y)` alinhando a barra de luz do DualShock 4 apontando para cima com a esfera do PS Move (`+Y_move`, `+4400` counts/G em repouso) e o touchpad com os botões frontais (`+Z_move`).
  - **Sincronia de Light Bar & Vibração + UI Renovada (`ui/pages/ds4_page.py`, `ui/mixins/ds4_handlers.py`, `sensor/tracking_overlay.py`):** Novo cartão **PLAYSTATION MOVE EMULATOR (NATIVE ZCM2)** dentro de `ds4_info_frame` com amostra RGB ao vivo da esfera e toggle **Sync DS4 Light Bar & Rumble with PS Move Sphere** (`ds4_sync_lightbar`), além do HUD OpenCV atualizado com orbe RGB ao vivo e legenda de botões PS Move.
  - **Remoção Completa do Legado Virtual Phone (`/smartphone`):** Excluídos definitivamente `sensor/virtual_phone.py`, `sensor/vphone_protocol.py`, `tests/test_vphone_protocol.py`, `ui/benchmark_dialog.py`, `ui/mixins/ds4_vphone_handlers.py`, todas as chaves `virtual_phone_*`/`benchmark_auto_record` de `config.json` e todos os blocos/widgets de Virtual Phone da UI Qt 6.

---

## Roadmap Futuro

1. **Modo Background / Headless:**
   - *Planejado:* Uma flag `--no-gui` que desativa a criação da janela OpenCV `cv2.imshow()`, permitindo que todo o poder da placa de vídeo e CPU seja 100% dedicado ao Just Dance PC em computadores mais modestos.
