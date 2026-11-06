# 🕺 Legacy Sensor Lite — Sensor de Movimento para Just Dance PC

**Legacy Sensor Lite** é um sensor de movimento corporal de alto desempenho, ultraleve e direto ao ponto para o jogo **Just Dance PC (Legacy Offline)**, unificando o suporte a **Webcams USB/Integradas** e à **PlayStation Camera** (PS4 Camera em até 60 FPS).

---

## ⚡ Principais Recursos

- **Zero Bloatware:** Apenas o que importa: abrir, escolher a câmera e jogar. Inicialização instantânea e consumo mínimo de CPU/RAM.
- **Suporte Nativo a PlayStation Camera:**
  - Presets otimizados para PS4 Camera (**1280x800 @ 60 FPS**) e PS3 Eye (**640x480 @ 60 FPS**).
  - Integração e detecção automática do driver **PSCam4Win**.
- **Suporte a Webcams USB e Integradas:**
  - Presets de 640x480 @ 30 FPS, 720p HD e 1080p Full HD.
- **Rastreamento de Alta Fidelidade com MediaPipe Pose:**
  - Mapeamento exato dos 20 joints padrão do Kinect v1.
  - **Filtro Hand Anchor:** Extrapolação anatômica do vetor do antebraço para que movimentos rápidos com as mãos nunca percam o rastreamento durante as danças.
  - **Suavização Dinâmica Anti-Jitter (EMA):** Filtro adaptativo com base na velocidade para eliminar tremores em poses estáticas e manter latência zero em passos rápidos.
  - **Calibração de Altura Automática e Manual:** Normaliza as proporções do corpo diretamente para o espaço de coordenadas esperado pelo jogo.
- **Comunicação Direta por Memória Compartilhada:**
  - Comunica-se com o Just Dance através da memória compartilhada do Windows `Local\LegacyWebcamKinectPose` via seqlock lockless (344 bytes), lido diretamente pelo `Kinect10.dll`.
- **HUD Elegante e Teclas Rápidas:**
  - Overlay de esqueleto em cores vibrantes, contadores de FPS da câmera e do rastreamento.
  - Teclas rápidas: `[C]` Recalibrar, `[M]` Espelhar tela, `[H]` Ocultar HUD, `[ESC / Q]` Fechar.

---

## 🚀 Como Usar

### 1. Instalar a DLL no Just Dance
1. Na pasta `Kinect for Legacy DLL`, copie o arquivo **`Kinect10.dll`**.
2. Cole-o na pasta raiz da sua instalação do **Just Dance PC** (onde está o executável do jogo), substituindo o existente se houver.
*(No menu do Legacy Sensor Lite há um botão direto "Abrir Pasta do Kinect10.dll" para facilitar).*

### 2. Executar o Sensor
- Dê um duplo-clique no executável **`LegacySensor.exe`** (ou execute **`INICIAR_SENSOR.bat`**) para abrir o painel de controle e gerenciar suas configurações.

### 3. No Menu de Configuração
1. Selecione o tipo de câmera:
   - **🎮 PlayStation Camera:** Para usar a PS4 Camera ou PS3 Eye em 60 FPS via PSCam4Win.
   - **📷 Webcam Padrão:** Para webcams USB ou de notebooks.
2. Escolha o dispositivo e o preset desejado (ex: `1280x800 @ 60 FPS` ou `640x480 @ 30 FPS`).
3. Mantenha **"Espelhar Câmera Horizontalmente"** ativado para que a tela espelhe seus movimentos corporais como no espelho.
4. Clique em **"▶ INICIAR RASTREAMENTO"**.

### 4. No Jogo (Just Dance PC)
1. Inicie o Just Dance PC.
2. Na tela de seleção de controle, escolha **Kinect Sensor**.
3. Escolha sua música e divirta-se!

---

## ⌨️ Atalhos Durante o Jogo / Rastreamento

| Tecla | Função |
|---|---|
| **C** | Recalibra o centro dos quadris e a altura do corpo |
| **M** | Alterna o espelhamento horizontal da câmera |
| **H** | Mostra ou oculta o HUD de texto da tela |
| **Q** ou **ESC** | Encerra a janela de rastreamento e retorna ao menu |

---

## 🎮 Dicas para PlayStation 4 Camera (PS4 Camera)

- Para atingir os **60 FPS estáveis**, certifique-se de que o **PSCam4Win** está ativo (o launcher avisa o status do driver em tempo real).
- A interface seleciona automaticamente a PS4 Camera e bloqueia o início caso a câmera seja desconectada, impedindo o uso indevido da webcam.
- Selecione a resolução **1280x800 @ 60 FPS** para máxima precisão nos passos de dança.
- Posicione a câmera a cerca de **1,8 a 2,5 metros** de distância para enquadrar o corpo por inteiro.

---

## 📁 Estrutura Modular do Projeto

- `main.py`: Ponto de entrada do sistema (despachante CLI e inicializador).
- `test_suite.py`: Suíte de testes automatizados completa (9/9).
- `config.json`: Persistência das configurações locais do usuário.
- `sensor/`: Pacote com o motor de visão computacional, câmera, IA, IPC e sessão.
  - `sensor/camera_manager.py`: Gerenciamento de câmeras, PnP e integração PSCam4Win.
  - `sensor/pose_tracker.py`: Motor MediaPipe Pose, Hand Anchor e Calibrador Multi-Tier.
  - `sensor/kinect_shared_memory.py`: Driver IPC da memória compartilhada (`JDP1`, `JMI1/2`, `JXC1`).
  - `sensor/tracking_session.py`: Orquestrador do loop de rastreamento e eventos.
  - `sensor/tracking_overlay.py`: Renderizador de silhueta, contorno neon e HUD em OpenCV.
  - `sensor/config_manager.py`: Persistência de configurações em `config.json`.
- `ui/`: Pacote com a interface gráfica de usuário em Tkinter / ttk (`ui/gui.py`).
- `assets/`: Recursos visuais e mídias (`assets/IconePSCAMERA.png` e modelos).
- `models/`: Modelo de rede neural pré-treinado (`models/pose_landmarker_lite.task`).
- `tools/`: Utilitários e instalador oficial do driver (`tools/PSCam4Win-Setup.exe`).
- `Kinect for Legacy DLL/`: DLL proxy de 32 bits para a pasta do Just Dance PC (`Kinect10.dll`).
