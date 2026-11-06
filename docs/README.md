# 🕺 Legacy Sensor Lite — Documentação Geral do Projeto

O **Legacy Sensor Lite** é um sensor de movimento corporal de alta precisão, latência ultrabaixa e zero bloatware projetado para o jogo **Just Dance PC (Legacy Offline)**. Ele unifica o suporte para **Webcams USB/Integradas** e para a **PlayStation 4 Camera** (PS4 Camera via driver PSCam4Win em 1280x800 @ 60 FPS estáveis).

---

## 🎯 Objetivo do Projeto

O emulador original da comunidade acumulou centenas de megabytes de recursos secundários (como músicas de menu em MP3, sistemas de moedas, XP, presentes, vídeos e telemetria) que tornavam o aplicativo pesado (~632 MB) e lento para inicializar.

O **Legacy Sensor Lite** foi reconstruído do zero com um único propósito:
> **"Abrir, selecionar a câmera e ir direto dançar."**

Eliminamos todo o conteúdo extra mantendo e aperfeiçoando os pilares que realmente importam:
1. **Rastreamento de corpo anatômico** via MediaPipe Pose Tasks API com Hand Anchor Filter.
2. **Taxa de quadros de 60 FPS** com suporte dedicado à PlayStation 4 Camera.
3. **Ponte de memória compartilhada completa (Pose + Imagem/Máscara)** com protocolo seqlock atômico lido pelo `Kinect10.dll` do Just Dance PC.
4. **Prévia com Silhueta ("Sombrinha") e Contorno Neon**, restaurando o feedback visual clássico tanto na janela do sensor quanto no menu de seleção e HUD do Just Dance PC.

---

## 🚀 Funcionalidades Principais

| Recurso | Descrição | Status |
|---|---|---|
| **Rastreamento Esquelético (20 Joints)** | Converte a pose do corpo humano para o formato binário de 20 articulações consumido pelo Just Dance PC. | Implementado |
| **Silhueta e Contorno Neon ("Sombrinha")** | Gera máscara de segmentação anatômica em tempo real, renderizando a sombrinha neon e alimentando o Just Dance PC. | Implementado |
| **Ponte de Imagem e Profundidade (JMI1)** | Buffer `Local\LegacyWebcamKinectImage` (1.3 MB) transmitindo imagem BGRA e máscara do jogador ao jogo. | Implementado |
| **Suporte à PlayStation 4 Camera** | Presets otimizados para a PS4 Camera em **1280x800 @ 60 FPS** (YUY2/NV12 nativo sem conversões pesadas). | Implementado |
| **Hotplug e Auto-Detecção em Tempo Real** | Detecção instantânea de conexões e desconexões de câmeras via PnP Win32 (< 3ms) sem congelar o menu. | Implementado |
| **Suporte a Webcams USB/Integradas** | Detecção de câmeras plug-and-play em 640x480, 720p HD e 1080p. | Implementado |
| **Filtro Hand Anchor** | Extrapolação do vetor de antebraço para manter o rastreamento das mãos mesmo durante giros e passos velozes. | Implementado |
| **Suavização Adaptativa Anti-Jitter** | Filtro EMA dinâmico: elimina tremedeiras em poses estáticas e zera a latência em movimentos rápidos. | Implementado |
| **Memória Compartilhada Windows (IPC)** | Buffers `Local\LegacyWebcamKinectPose` e `Local\LegacyWebcamKinectImage` com protocolo seqlock sem travar o jogo. | Implementado |
| **Otimização de Timer (30 FPS Fixos)** | Temporizador de alta precisão (1 ms) no Windows, elevando o HUD e esqueleto de 21 FPS para 30 FPS cravados sem quebrar a pontuação. | Implementado |
| **Perfis Simplificados e Auto-Altura** | Cartões interativos (Equilibrado, Competitivo, Ultra Estável) e normalização de altura 100% automática. | Implementado |
| **Menu Dark Moderno em Tkinter** | Interface leve com seletor de câmera, perfis simplificados, abas com ícones vetoriais e início rápido. | Implementado |
| **HUD de Jogo em OpenCV** | Visualização da silhueta sombreada, contorno e esqueleto desenhados com contadores reais de FPS. | Implementado |

---

## 🛠️ Tecnologias Utilizadas

- **Linguagem:** Python 3.10+ (testado e otimizado para Python 3.12 e 3.15).
- **Visão Computacional & IA:**
  - `opencv-python`: Captura de vídeo DirectShow/MSMF e renderização de HUD.
  - `mediapipe` (v1.2+ Tasks API): Inferência da rede neural `pose_landmarker_lite.task`.
  - `numpy`: Operações matemáticas de cinemática e buffers de vídeo.
- **Interface Gráfica:**
  - `tkinter` / `ttk`: Interface nativa estilizada com paleta escura (sem dependências de frameworks pesados).
- **Comunicação Interprocesso (IPC):**
  - Módulos `mmap` e `struct` da biblioteca padrão do Python.
  - `Kinect10.dll`: DLL proxy de 32 bits (Win32) que alimenta o processo do Just Dance PC.
- **Integração de Hardware:**
  - `PSCam4Win`: Driver em modo usuário (WinUSB + DirectShow Virtual Camera) para PlayStation 4 Camera (sensor OmniVision OV580 + OV9713).

---

## 📂 Estrutura de Diretórios Resumida

```
LegacySensor_Lite/
├── main.py                     # Ponto de entrada (CLI e despachante da aplicação)
├── test_suite.py               # 9 suítes completas de testes automatizados
├── config.json                 # Preferências salvas do usuário
├── sensor/                     # Pacote do Motor de Rastreamento e IA
│   ├── camera_manager.py       # Descoberta de câmeras e captura assíncrona
│   ├── pose_tracker.py         # Motor MediaPipe, Hand Anchor, Calibrador e EMA
│   ├── tracking_session.py     # Orquestrador do loop de rastreamento e eventos
│   ├── tracking_overlay.py     # Renderização visual do esqueleto, HUD e silhueta
│   ├── kinect_shared_memory.py # Driver IPC de memória compartilhada (JDP1, JMI1/2, JXC1)
│   └── config_manager.py       # Leitura e persistência de config.json
├── ui/                         # Pacote da Interface Gráfica
│   └── gui.py                  # Painel de controle e configurações (Tkinter dark)
├── assets/                     # Recursos visuais e mídias
│   ├── IconePSCAMERA.png       # Ícone da PlayStation 4 Camera
│   └── models/                 # Modelos neurais locais
├── models/
│   └── pose_landmarker_lite.task # Modelo pré-treinado do Google MediaPipe
├── tools/
│   ├── PSCam4Win-Setup.exe       # Instalador oficial do driver da PS4 Camera
│   └── get_cameras.ps1           # Helper de enumeração de dispositivos
└── Kinect for Legacy DLL/
    └── Kinect10.dll              # DLL de 32 bits a ser colocada no Just Dance PC
```

---

## ⚡ Primeiros Passos

1. **Copie a DLL para o Just Dance:**
   Coloque o arquivo [`Kinect10.dll`](../LegacySensor_Lite/Kinect%20for%20Legacy%20DLL/Kinect10.dll) na pasta onde está o executável do seu Just Dance PC.
2. **Execute o Sensor:**
   Dê um duplo clique em [`INICIAR_SENSOR.bat`](../LegacySensor_Lite/INICIAR_SENSOR.bat).
3. **Selecione a Câmera:**
   Escolha **PlayStation Camera** (se estiver usando a PS4 Camera conectada) ou **Webcam Padrão**.
4. **Inicie o Jogo:**
   Clique em **▶ INICIAR RASTREAMENTO**, abra o Just Dance PC e selecione o controle **Kinect**.
