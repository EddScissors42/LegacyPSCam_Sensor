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
| **Integração PlayStation 4 Camera** | ✅ Totalmente Implementado | `camera_manager.py` | Suporte nativo ao sensor OV580 em **1280x800 @ 60 FPS**, captura direta via FrameBus IPC (anti-tela preta) e auto-crop de Side-by-Side. |
| **Auto-Detecção de Hotplug e Reconexão** | ✅ Totalmente Implementado | `camera_manager.py` / `gui.py` | Monitoramento PnP de hardware via Win32 CfgMgr32 (< 3ms) com auto-seleção e atualização fluida sem congelar o menu. |
| **Máquina de Estados da PS4 Camera** | ✅ Totalmente Implementado | `camera_manager.py` / `gui.py` | Detecção em tempo real do ciclo de vida USB (Desconectada, Bootloader, Câmera Virtual e Pronta). |
| **Integração Webcams Padrão** | ✅ Totalmente Implementado | `camera_manager.py` | Suporte a webcams USB e embutidas em 30 e 60 FPS. |
| **Filtro Hand Anchor** | ✅ Totalmente Implementado | `pose_tracker.py` | Extrapolação do vetor de antebraço para mãos velozes. |
| **Suavização EMA Adaptativa** | ✅ Totalmente Implementado | `pose_tracker.py` | Filtro dinâmico sensível à velocidade (anti-jitter). |
| **Calibração de Escala e Eixos** | ✅ Totalmente Implementado | `pose_tracker.py` | Centralização dos quadris e conversão de eixos para o Just Dance. |
| **Interface Gráfica PlayStation 5 (Qt 6 / PySide6)** | ✅ Totalmente Implementado | `ui/gui_qt.py` | UI inspirada no console PlayStation 5 com animações fluidas de deslizamento horizontal entre abas (`SlidingStackedWidget` com curvas cúbicas), cartões com sombras e cantos arredondados, painel sensível a estado e fallback para Tkinter. |
| **Painel Sensível a Estado (Balão de Desconexão Único)** | ✅ Totalmente Implementado | `ui/gui_qt.py` / `icons.py` | Quando desconectado, o balão com 'X' grande e botão contextual é o **único elemento exibido**. Ao conectar, transita automaticamente para os controles de vídeo e opções adicionais. |
| **Perfis Simplificados e Auto-Altura** | ✅ Totalmente Implementado | `ui/gui_qt.py` / `config_manager.py` | 3 perfis estilo console (Equilibrado, Competitivo, Ultra Estável) e calibração de altura 100% automática. |
| **HUD de Jogo e Overlay OpenCV** | ✅ Totalmente Implementado | `tracking_overlay.py` | Renderização do esqueleto, silhueta e contadores reais de FPS. |
| **Interface de Linha de Comando (CLI)**| ✅ Totalmente Implementado | `main.py` | Flags `--start`, `--mode`, `--camera` e `--gui {qt,tkinter}`. |
| **Rastreamento Multi-Jogador (2P)** | 🟡 Parcialmente Implementado | `pose_tracker.py` | O MediaPipe suporta `num_poses=2`, mas o Lite foca em 1P. |
| **Auto-Framing / FaceFollow PTZ** | ✅ Totalmente Implementado | `pose_tracker.py` | Auto-framing digital com zoom suave (1.22x) e centralização dinâmica do rosto para a foto/avatar do dançarino no Just Dance. |
| **Celular Virtual (Emulador JD Controller via Câmera)** | ✅ Totalmente Implementado | `virtual_phone.py` / `ui/gui_qt.py` | Emula um smartphone conectado via WebSocket local (`/smartphone`) e converte o movimento 3D da mão na câmera em dados de acelerômetro 3D (`JD_PhoneScoringData`) e comandos de menu para músicas que só suportam controle de mão. |
| **DualShock 4 [EXPERIMENTAL]** | ✅ Totalmente Implementado | `sensor/ds4_controller.py` / `ui/gui_qt.py` | Driver nativo Bluetooth HID (500+ Hz) com handshake 0x11, leitura do acelerômetro 3D, feedback de botões, rumble háptico, telemetria em tempo real e ponte para o Just Dance via Virtual Phone. |
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

### 2. Integração Especializada com a PlayStation 4 Camera (OV580)
- **Como funciona:** A PS4 Camera é uma câmera estéreo equipada com o processador OmniVision OV580 e dois sensores OV9713, capaz de atingir 60 FPS com alta nitidez e amplo campo de visão horizontal.
- **Implementação:**
  - O `camera_manager.py` detecta a instalação e o status de execução do driver `PSCam4Win`.
  - **Leitura Direta via FrameBus IPC (Anti-Tela Preta):** Utiliza o leitor de memória compartilhada `FrameBusReader` para se conectar diretamente aos canais `Global\PSCam4Win{slot}.FrameBus`. Isso elimina a tela preta causada pelo cache do Windows Camera Frame Server que forçava 1280x400 no DirectShow e ativava o `FillYuy2Black` no driver.
  - **Auto-Crop de Stereo Side-by-Side (SBS):** Quando o driver inicializa no modo Side-by-Side (2560x800 ou 1280x400), o sistema detecta a proporção panorâmica (`w >= 1.8 * h`) e recorta automaticamente a metade correspondente ao sensor esquerdo (`frame[:, :w//2]`), entregando uma visão limpa de 16:10 do dançarino sem duplicação estéreo.
  - Configura a câmera virtual DirectShow para operar em **1280x800 @ 60 FPS**.
  - Mantém o FourCC original do driver em **YUY2 / NV12**, sem tentar forçar compactação MJPG incompatível.
  - Oferece no menu a detecção em tempo real e o botão para iniciar o driver caso ele esteja parado.

### 3. Filtro Hand Anchor (Extrapolação Anatômica)
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
  - **Menu Superior Centralizado de 3 Abas:** As abas "Video Settings", "Calibration" e "Experimental" ficam perfeitamente centralizadas no topo do painel principal, cada uma com seu respectivo ícone supersampleado (`settings.svg`, `sliders.svg` e `lab.svg`).
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
  - **Protocolo WebSocket Nativo UbiArt Multi-Geração (`v1` e `v2`):**
    - Cliente WebSocket RFC 6455 puro (zero dependências externas) com negociação híbrida de subprotocolos (`v1.phonescoring.jd.ubisoft.com, v2.phonescoring.jd.ubisoft.com`), garantindo compatibilidade instantânea tanto com o **Just Dance 2017 / 2018 (Legacy Offline)** quanto com versões modernas (**Just Dance 2020–2022 / Dreyn Mod**).
    - Conexão adaptativa com prioridade para TCP plano (`ws://127.0.0.1:8080/smartphone`) e fallback para TLS/SSL (`wss://`), eliminando erros de protocolo (`1002 CLOSE_PROTOCOL_ERROR`) e atrasos de handshake.
    - Executa a máquina de estados oficial de 5 etapas (`JD_PhoneDataCmdHandshakeHello` -> `JD_PhoneDataCmdHandshakeContinue` -> `JD_PhoneDataCmdSync` -> `JD_PhoneDataCmdSyncStart` -> `JD_PhoneDataCmdSyncEnd`), sincronizando o perfil do dançarino (`JD_ProfilePhoneUiData`) e identificando o dançarino como Jogador 1.
    - **Verificação Constante e Resiliência a Janela sem Foco (AFK):** Mantém a verificação ativa a cada 1s com auto-descoberta UDP (`6000`/`7000`) e preserva o socket aberto pacientemente mesmo quando a janela do Just Dance está sem foco (loop principal pausado), completando o pareamento no exato instante em que o jogador foca na janela do jogo.
    - Suporte dinâmico a `JD_ProfilePhoneUiData` (exibindo o nome do perfil do jogador conectado) e `JD_InputCollectionPhoneData` (`availableInput` com booleanos `touchOn: true/false`).
  - **Motor Físico `HandAccelerometer` Refinado (Cinemática Rotacional + EMA Adaptativo):**
    - **Filtro EMA Dinâmico com Latência Zero em Picos:** Em repouso ou movimentos lentos ($\le 0,20\text{ m/s}$), aplica $\alpha = 0,45$ para anular tremores e garantir orientação gravitacional estável; em passos rápidos e gestos intensos ($\ge 0,85\text{ m/s}$), eleva $\alpha$ instantaneamente para **$0,95$**, eliminando o atraso de 60 ms e preservando a precisão no tempo da batida musical.
    - **Aceleração Centrífuga / Rotacional ($\vec{a}_c = v_{\text{tang}}^2 / L$):** Simula a força centrífuga radial ao longo do antebraço durante giros e movimentos em arco (ex: estilo "Windmill" e sweeps de *Smalltown Boy*), gerando os vetores de força G esperados pelo classificador do jogo.
    - **Escalação Física Real de Força G:** Escalonamento calibrado para atingir picos de $3,5\text{G}$ a $5,5\text{G}$ em golpes velozes, cruzando o `HighThreshold` do Just Dance para registrar **"Perfect"** e **"Super"**.
  - **Gravador de Telemetria CSV Embutido (`Record Log`):**
    - Permite gravar em tempo real os dados de acelerômetro 3D, velocidade da mão, $\alpha$ do filtro e coordenadas em `logs/vphone_accel_<timestamp>.csv` para análise diagnóstica e comparação direta com logs de celulares reais.
  - **Interface Unificada e Padronizada em Inglês (Design Consistente com Calibração):**
    - Chave geral **ON / OFF** com recolhimento dinâmico: quando desativado, toda a seção de acelerômetro e controles fica oculta para manter a interface limpa e direta.
    - Indicador de status em tempo real e leitura ao vivo do acelerômetro 3D em linha dedicada abaixo do status.
    - **Visibilidade Condicional do 3D Acelerômetro:** O mostrador de acelerômetro 3D só é renderizado e visível durante o rastreamento ativo (`START TRACKING`), ficando oculto quando inativo para manter o layout limpo.
    - IP e Porta ocultos da visão para evitar poluição visual (mantendo valores padrão `127.0.0.1:8080` de forma transparente).
    - Botões com contorno elegante (`border: 1px solid #CBD5E1`) para **Reconnect**, **Auto-Find**, **Skip Finish** e **Record Log**.
    - Atualização do cabeçalho da sidebar para `"ooomaga :O"` e dica de DLL clarificada para `"Copy Kinect10.dll to the game folder (only for Legacy Offline PC)"`.
    - Tipografia de alto contraste com cores escuras explícitas (`#0F172A`) para "TRACKED HAND" e "SENSITIVITY", eliminando problemas de texto branco/invisível em temas escuros do Windows e seguindo rigorosamente o padrão visual da aba de Calibração.

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
      - `[L1] / [R1]` no DualShock 4 (ou `[` / `]` e `A` / `D` no teclado): Alterna ciclicamente o Coach / NPC selecionado na sala de dança (`JD_ChangeCoach_PhoneCommandData`), com pulso de vibração tátil de confirmação no controle.
      - `[✕]` (Botão X) no DualShock 4 (ou `Enter` / `Space` no teclado): Confirma seleções e inicia a dança (`VALID` / `START_GAME`), com pulso de vibração tátil duplo.
      - `[Q]`: Encerra o rastreamento e fecha a janela de telemetria de forma limpa.
      - `[R]`: Reconecta imediatamente o controle DualShock 4 via Bluetooth com confirmação de vibração tátil.

---

## 🟡 Funcionalidades Parciais e ⏳ Roadmap Futuro

1. **Rastreamento Multi-Jogador (2 Jogadores):**
   - *Estado Atual:* O modelo MediaPipe já suporta carregar 2 poses (`num_poses=2`), mas o mapeamento do Lite prioriza 1 jogador (Player 1) para manter a CPU o mais leve possível a 60 FPS. A extensão para alimentar dois esqueletos simultâneos na memória compartilhada está estruturada no pipeline.
2. **Modo Background / Headless:**
   - *Planejado:* Uma flag `--no-gui` que desativa a criação da janela OpenCV `cv2.imshow()`, permitindo que todo o poder da placa de vídeo e CPU seja 100% dedicado ao Just Dance PC em computadores mais modestos.
