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
| **Interface Gráfica PlayStation 5 (Qt 6 / PySide6)** | ✅ Totalmente Implementado | `ui/gui_qt.py` / `ui/pages.py` | UI inspirada no console PlayStation 5 com animações fluidas de deslizamento horizontal entre abas (`SlidingStackedWidget` com curvas cúbicas), cartões com sombras e cantos arredondados e painel sensível a estado. |
| **Painel Sensível a Estado (Balão de Desconexão Único)** | ✅ Totalmente Implementado | `ui/gui_qt.py` / `icons.py` | Quando desconectado, o balão com 'X' grande e botão contextual é o **único elemento exibido**. Ao conectar, transita automaticamente para os controles de vídeo e opções adicionais. |
| **Perfis Simplificados e Auto-Altura** | ✅ Totalmente Implementado | `ui/gui_qt.py` / `config_manager.py` | 2 perfis otimizados (Balanced / Full, Competitive / Lite) e calibração de altura 100% automática. |
| **HUD de Jogo e Overlay OpenCV** | ✅ Totalmente Implementado | `tracking_overlay.py` | Renderização do esqueleto, silhueta e contadores reais de FPS. |
| **Interface de Linha de Comando (CLI)**| ✅ Totalmente Implementado | `main.py` | Flags `--start`, `--mode {pscam,webcam,ds4}` e `--camera`. |
| **Rastreamento Multi-Jogador (2P Duo) & Memória Anti-Swap** | ✅ Totalmente Implementado | `sensor/player_slot.py` / `pose_tracker.py` | Rastreia até 2 dançarinos simultâneos (P1 Azul e P2 Laranja Claro) via `JDP2` (664B) e `JMI2` (máscara indexada 1 e 2), com memória persistente de identidade (`LongTermIdentityProfile`) resistente a valsas, cruzamentos e saídas temporárias. |
| **Auto-Framing / FaceFollow PTZ** | ✅ Totalmente Implementado | `pose_filters.py` / `tracking_session.py` | Auto-framing digital com zoom suave (1.22x) e alinhamento de frustum 3D→2D (`warpAffine`) em modo 1P (desativado automaticamente em 2P para nunca cortar o segundo jogador). |
| **Celular Virtual (Emulador JD Controller via Câmera)** | ✅ Totalmente Implementado | `virtual_phone.py` / `ui/gui_qt.py` | Emula um smartphone conectado via WebSocket local (`/smartphone`) e converte o movimento 3D da mão na câmera em dados de acelerômetro 3D (`JD_PhoneScoringData`) e comandos de menu para músicas que só suportam controle de mão. |
| **DualShock 4 & Controles Compatíveis (Nível A) [EXPERIMENTAL]** | ✅ Totalmente Implementado | `sensor/ds4_controller.py` / `ui/gui_qt.py` | Driver nativo Bluetooth/USB HID (500+ Hz) com suporte a DS4 original, controles licenciados de terceiros (Hori, Nacon, Razer, Astro, Scuf) e clones/réplicas (ShanWan, DragonRise) com diagnóstico automático de IMU congelado (0G). |
| **Benchmark de Telemetria & Calibração Adaptativa** | 🔒 Preservado / Oculto na UI | `sensor/telemetry_benchmark.py` / `ui/benchmark_dialog.py` | Módulo de benchmark comparativo de aceleração (Câmera vs DS4) e auto-gravação por música preservado no código, porém desabilitado por padrão e removido da interface visual para manter o design enxuto. |
| **Visão Estéreo (Stereo Vision) para PS4 Camera** | ✅ Totalmente Implementado | `sensor/stereo_matcher.py` / `ui/gui_qt.py` | Calibração de fábrica ($B=85.2\text{ mm}$), auto-alinhamento vertical dinâmico das lentes ($\Delta y$), triangulação 3D sub-pixel via Fluxo Óptico Piramidal (`PyrLK`, <0.5ms) e suavização temporal EMA da silhueta. |
| **Emulate Kinect (Zero-File-Replacement Mode)** | ✅ Totalmente Implementado | `sensor/kinect_emulator.py` / `ui/pages.py` | Emulação do sensor Kinect diretamente na memória RAM do Just Dance Legacy (32-bit) via `Legacy10.dll` + Ponte de Memória Compartilhada, sem substituir a `Kinect10.dll` original na pasta do jogo. |
| **Camera Warm-Up em Background & Standby Throttling** | ✅ Totalmente Implementado | `sensor/camera_manager.py` / `ui/gui_qt.py` | Pré-negociação assíncrona da câmera em standby (<0.4% CPU) 400ms após abertura da GUI, eliminando a espera de 2.3s ao clicar em "START TRACKING" para ~0.3s (~84% mais rápido). |
| **Lazy Loading Estendido PEP 562 & Startup Otimizado** | ✅ Totalmente Implementado | `sensor/__init__.py` / `ui/gui_qt.py` | Carregamento sob demanda de submódulos secundários (`phone_camera`, `virtual_phone`, `ds4_controller`, `telemetry_benchmark`) para inicialização ultrarrápida da aplicação. |
| **Modo Headless (Sem Janela)** | ⏳ Planejado | `tracking_session.py` | Rastrear em background sem gastar GPU com janela gráfica. |

---

## 🔍 Detalhamento das Funcionalidades Implementadas

### 1. Simulador do Kinect v1 para Just Dance PC
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
  - **Triangulação 3D Sub-Pixel (`PyrLK` + Banda Epipolar 2D):** Realiza busca em banda 2D com interpolação parabólica seguida de refinamento por Fluxo Óptico Piramidal Lucas-Kanade (`cv2.calcOpticalFlowPyrLK`) nas 20 articulações corporais (< 0.5 ms). Substitui a profundidade estática $Z \approx 2.0\text{m}$ por medição métrica física real ($Z = \frac{f \cdot B}{d}$).
  - **Auto-Calibração Epipolar Vertical Dinâmica (`vertical_offset_px`):** Mede e compensa automaticamente em background pequenas diferenças de inclinação vertical ($\Delta y$) entre a lente esquerda e a direita da unidade física da câmera, dispensando calibração com tabuleiro de xadrez.
  - **Suavização Temporal EMA na Silhueta (`_seg_prob_ema`):** Suaviza temporalmente o tensor de probabilidade da máscara de segmentação do MediaPipe antes da binarização, eliminando tremulações de ruído ISO em 60 FPS sem usar `StereoSGBM` denso.
- **Modos Disponíveis (Aba Experimental da UI):**
  - **`Desativado` (Padrão):** Opera em modo monocular clássico com custo zero de CPU adicional.
  - **`Ativado (Sub-Pixel PyrLK 3D)`:** Ativa a triangulação 3D sub-pixel com auto-alinhamento das lentes, mantendo 60 FPS estáveis.

### 3.1 Sistema Modular "Person Lock-In" (`sensor/person_lock.py` & `sensor/pose_filters.py`)
- **Objetivo:** Fazer o rastreador "grudar" no dançarino ativo e jamais perder o esqueleto ou a silhueta em giros rápidos de 360°, oclusões momentâneas, passos largos ou quando outra pessoa passa pelo ambiente, mantendo **60 FPS cravados** (< 0.25 ms de custo combinado).
- **Arquitetura 100% Modular (Hot-Reload & Zero-Cost Bypass):**
  - Controlado pela chave mestra `person_lock_enabled` e pelas chaves individuais `inertial_coasting_enabled`, `dancer_lock_enabled`, `dancer_lock_roi_focus`, `face_follow_spin_fallback` e `face_follow_adaptive_zoom`. Quando desabilitado, cada módulo executa *short-circuit* imediato (0.000 ms), pronto para futuros controles de UI em hardwares modestos.
- **Os 3 Pilares Implementados:**
  1. **Predição Inercial em Micro-Quedas (`InertialCoastingFilter`):** Quando a rede neural perde o corpo por até `250 ms` (~15 frames a 60 FPS durante um giro de 360° ou *motion blur*), o filtro mantém `is_tracked = True` e projeta as 20 articulações 3D e 2D usando velocidade física amortecida ($\gamma = 0.82$), deslocando também a máscara de silhueta `320x240` e aplicando interpolação suave (*re-entry LERP*) por 3 frames ao readquirir o jogador.
  2. **Trava de Jogador Ativo por Cor e Espaço (`DancerIdentityLock`):** Memoriza um histograma 2D Matiz-Saturação (HSV 12x8 bins) da roupa/tronco do jogador e monitora a continuidade espacial da caixa delimitadora. Rejeita saltos impossíveis para objetos de fundo ou pessoas passando com outra cor de roupa, além de atenuar suavemente regiões periféricas distantes no buffer privado da IA (`apply_roi_focus`).
  3. **Auto-Framing Dinâmico de Corpo Inteiro (`FaceFollowPTZ` Aprimorado):** Inclui fallback anatômico anti-giro (extrapola a posição da cabeça pelo vetor `HipCenter -> ShoulderCenter` quando o rosto fica oculto de costas), deadzone central anti-trepidação e zoom adaptativo de corpo inteiro que abre o enquadramento automaticamente quando o jogador ergue os braços ou abre a base.

### 4. Filtro Hand Anchor (Extrapolação Anatômica)
- **Problema resolvido:** Em coreografias de dança com giros rápidos ou mãos próximas ao tronco, as redes neurais de detecção de pose frequentemente perdem a visibilidade dos dedos (`INDEX` e `WRIST`), fazendo a mão "pular" para coordenadas inválidas e gerando notas `MISS` ou `OK`.
- **Implementação:** O `HandAnchorFilter` calcula o vetor diretor 3D que vai do cotovelo até o pulso (`vetor = pulso - cotovelo`) e, caso a confiança dos dedos caia, projeta a ponta da mão ao longo dessa linha anatômica natural por uma distância proporcional de 12 centímetros.

### 4. Suavização Dinâmica Anti-Jitter (Adaptive Dynamic EMA)
- **Problema resolvido:** Filtros de suavização comuns adicionam atraso (*lag*) em movimentos rápidos ou deixam as mãos tremendo em poses paradas.
- **Implementação:** O `AdaptiveSmoother` mede a velocidade instantânea de cada articulação entre quadros consecutivos:
  - Movimentos lentos ou poses estáticas (< 0.05 m/s): utiliza fator alpha baixo (~0.25 a 0.35), resultando em um esqueleto perfeitamente estável e sem tremedeira.
  - Movimentos rápidos ou passos rítmicos (> 0.20 m/s): o alpha escala dinamicamente até 0.85+, entregando resposta imediata aos passos de dança.

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
  - **3 Perfis Simplificados em Cartões Interativos:**
    1. ⭐ **Equilibrado (`balanced`)**: EMA 0.55 / Confiança 0.50 (Padrão recomendado para a maioria das músicas).
    2. ⚡ **Competitivo (`competitive`)**: EMA 0.75 / Confiança 0.45 (Resposta ultrarrápida para coreografias velozes/extremas).
    3. 🛡️ **Ultra Estável (`stable`)**: EMA 0.35 / Confiança 0.40 (Máxima filtragem de ruído para ambientes com pouca luz).
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
  - **Temporizador de Alta Resolução de 1 ms no Python (`set_high_resolution_timer`):** No [tracking_session.py](file:///C:/Users/reydn/OneDrive/Documents/Projetos/LegacyPSCam_Sensor/sensor/tracking_session.py), ativamos `winmm.timeBeginPeriod(1)` e `ntdll.NtSetTimerResolution(10000, 1, ...)`. Com resolução de 1,0 ms no Windows, o `Sleep(33)` acorda exatamente a cada **33,6 ms**, elevando a taxa de 21 FPS para **30 FPS cravados**, que é o teto máximo e ótimo da engine do Just Dance.

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
    - Botão **Dim Screen** posicionado abaixo das duas opções de câmera, ativando tela preta e reduzindo renderização GPU do vídeo mantendo o stream WebSocket ativo.
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
- **Motor Multi-Jogador Desacoplado (`sensor/player_slot.py` & `sensor/pose_tracker.py`):**
  - Suporta nativamente **1 Jogador (Solo)** e **2 Jogadores (Duo)**.
  - **Oversampling de 4 Poses com Filtro Anatômico (`is_plausible_human_dancer`):** Em modo 2P, o detector MediaPipe opera com `num_poses=4` para propor múltiplos candidatos. Cada candidato é inspecionado por um filtro anatômico rigoroso que valida verticalidade, ombros acima dos quadris, largura e altura mínimas e score de confiança dos joints-chave, rejeitando instantaneamente cadeiras, casacos, almofadas ou móveis de fundo antes de ordenar os candidatos e atribuir os slots.
  - **Resolução de Inferência 640px (`INFER_MAX_W_2P = 640`):** Buffer de inferência em 640px de largura (ganho de 78% em densidade de amostragem em relação a 480px), mantendo braços e pernas nítidos a até 3 metros da câmera sem sobrecarregar a CPU.
  - Cada jogador possui sua própria instância isolada `PlayerSlotState` (`HandAnchorFilter`, `AdaptiveSmoother`, `SkeletonCalibrator`, `CameraSpaceXTracker`, `PersonLockController`, suavização temporal de segmentação `_seg_prob_ema` e `LongTermIdentityProfile`).
- **Memória de Identidade Anti-Swap (`LongTermIdentityProfile` & `MultiPlayerAssociator`):**
  - Resolve o problema histórico do Kinect de inverter Jogador 1 e Jogador 2 durante valsas, abraços ou cruzamentos rápidos:
    1. **Assinatura Visual Multi-Região Avançada (`AppearanceSignature`):** Combina histograma HSV 16x8 da camisa/torso (35%), perfil de luminosidade V da camisa (20%), histograma HSV 12x6 da calça/pernas (15%), perfil de luminosidade V da calça (10%), razão de contraste de brilho tronco/pernas (10%) e proporção relativa de altura corporal (10%). Permite discriminar dançarinos com precisão mesmo quando ambos vestem roupas escuras ou neutras.
    2. **Memória Âncora Permanente (`anchor_sig`) vs. Assinatura Viva (`live_sig`):** Consolida a identidade nos primeiros 25 quadros limpos e separados e mantém a âncora protegida durante toda a música (resetável com `[C] Recalibrate`).
    3. **Guarda de Proximidade / Valsa (`is_crowded`) & Trava de Aglomeração:** Congela instantaneamente o aprendizado de cor quando as caixas delimitadoras se aproximam (`dist < 0.22` ou `IoU > 0.08`), impedindo contaminação da memória. Trava trocas impulsivas de slot enquanto os dançarinos permanecerem sobrepostos.
    4. **Inércia de Slot (`CURRENT_SLOT_INERTIA_BONUS = 0.35`) & Momentum Cinemático Direcional:** Aplica desconto de custo para preservar o slot anterior e calcula o alinhamento vetorial da velocidade $(\vec{v} \cdot \vec{d})$, guiando os dançarinos com segurança através de cruzamentos em alta velocidade.
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
  - Quando **2 Players (Duo)** é selecionado na aba **Calibration**, um banner de aviso logo abaixo da seleção de modelo orienta que o **Lite AI** é o modelo ideal para sustentar FPS estável na CPU com 2 jogadores.

### 35. Modernização Visual do HUD & Efeitos Gamificados de Rastreamento (v0.9.1 Alpha)
- **Cápsulas Flutuantes Estilo Glass Pills (`draw_rounded_glass_pill`):**
  - Substituição das antigas barras pretas horizontais opacas que cortavam o topo e a base da tela por cápsulas flutuantes com cantos arredondados, fundo de vidro escuro translúcido (`alpha=0.62`) e bordas sutis neon/azuladas.
  - **Distribuição Anatômica Inteligente:**
    - **Pílula Superior Esquerda:** Branding da aplicação ("LEGACY PSCAM") e modelo/resolução da câmera.
    - **Pílula Superior Central:** Status do dançarino (`TRACKING ACTIVE` / `SEARCHING`), nível de calibração (`FULL BODY` / `UPPER BODY`) e indicador de slots ativos (`P1` em Azul e `P2` em Laranja Claro).
    - **Pílula Superior Direita:** Métricas em tempo real de FPS da câmera, FPS do pipeline de tracking e integridade da ponte IPC (`Kinect JDP1/JMI1`).
    - **Pílula Inferior Central:** Badges compactos dos atalhos de teclado (`[C] Calibrar • [M] Espelho • [H] Ciclar HUD • [Q/ESC] Sair`), liberando completamente os cantos inferiores da tela para que os pés dos dançarinos fiquem 100% visíveis em corpo inteiro.
- **Ciclo de Modos de HUD (`[H]`):**
  - **Modo 0 (Full HUD):** Exibe todas as métricas detalhadas (câmera, FPS, IPC e atalhos).
  - **Modo 1 (Minimalist / Clean Dance):** Exibe apenas a pílula central com o status dos dançarinos e indicador de calibração, reduzindo distrações na tela.
  - **Modo 2 (Off / Immersive Mirror):** Desativa completamente todo o HUD textual, mantendo apenas a silhueta do jogador e o esqueleto anatômico para uma experiência de espelho de dança totalmente imersiva.
- **Anel de Progresso Radial de Gesto (`draw_gesture_feedback`):**
  - Ao erguer a mão por 1.5–2.0 segundos para disparar o comando de `[ENTER]`, um anel radial de progresso neon (`cv2.ellipse` de 0° a 360°) renderiza diretamente ao redor da mão erguida do jogador, acompanhando seu movimento em tempo real.
  - Inclui ponto luminoso orbitante indicador de progresso e, ao atingir 100%, emite ondas concêntricas expansivas verdes com aviso luminoso `ENTER SENT!`.
- **Aura Dinâmica na Mão de Pontuação (Scoring Hand Aura):**
  - O jogador que utiliza a emulação de celular (Virtual Phone) recebe um halo pulsante e anéis radiantes na mão ativa de pontuação (mão direita ou esquerda configurada).
  - O raio e o brilho do halo reagem dinamicamente à velocidade instantânea do braço (`hand_speed`), oferecendo feedback visual imediato para movimentos rápidos e viradas de dança.
- **Contorno Neon Duplo na Silhueta (`draw_player_silhouette`):**
  - O contorno da silhueta foi aprimorado com uma camada dupla: um glow suave colorido de 3px com interpolação anti-aliasing seguido por uma linha de acabamento interna ultra-nítida de 1px, resultando em um visual moderno com identidade visual limpa.

---

## Roadmap Futuro

1. **Modo Background / Headless:**
   - *Planejado:* Uma flag `--no-gui` que desativa a criação da janela OpenCV `cv2.imshow()`, permitindo que todo o poder da placa de vídeo e CPU seja 100% dedicado ao Just Dance PC em computadores mais modestos.
