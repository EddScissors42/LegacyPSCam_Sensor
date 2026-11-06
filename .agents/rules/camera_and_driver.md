# Regra Especializada — Câmeras, DirectShow e Driver da PlayStation Camera

Esta regra aplica-se a qualquer modificação em `camera_manager.py`, na inicialização de dispositivos OpenCV (`cv2.VideoCapture`) e na integração com o driver `PSCam4Win`.

---

## 1. Suporte e Negociação com a PlayStation Camera (PSCam4Win)

- A PlayStation 4 Camera (e a PS3 Eye) funciona no Windows 11 através da Câmera Virtual nativa registrada pelo **PSCam4Win** (`PSCam4Win.dll` / `PSCam4WinTray.exe`).
- **Resoluções e Formatos:**
  - PS4 Camera suporta nativamente **1280x800 @ 60 FPS**, **640x400 @ 60 FPS** ou até 120 FPS.
  - PS3 Eye suporta nativamente **640x480 @ 60 FPS**.
  - O formato de pixel nativo entregue pelo DirectShow do PSCam4Win é **YUY2** ou **NV12**.
- **Regra do FourCC:**
  - NUNCA defina `cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))` quando o dispositivo for uma PlayStation Camera (`is_pscam=True`). Forçar MJPG em dispositivos YUY2/NV12 corrompe a negociação de mídia do DirectShow no Windows.
  - O FourCC `'MJPG'` deve ser utilizado somente para webcams USB genéricas que necessitam de compressão para atingir 60 FPS.

---

## 2. Captura Assíncrona com Latência Zero (`LatestFrameCamera`)

- Webcams no Windows usando DirectShow podem acumular buffers internos de 2 a 3 quadros quando o processamento demora, gerando um atraso visual perceptível (input lag na dança).
- O `LatestFrameCamera` resolve isso rodando uma thread dedicada de leitura contínua com uma fila (`threading.Lock`) que armazena apenas o **último frame mais recente**.
- **Regras de Performance:**
  - Não execute `frame.copy()` desnecessário dentro do lock de leitura para evitar alocações repetidas de memória a 60 FPS (~185 MB/s de cópias redundantes de buffer).
  - Trate quedas temporárias de frame (`ret is False`) sem travar a thread. Sempre inclua um `cv2.waitKey(5)` no loop principal de exibição para bombear a fila de eventos do Windows, evitando que a janela do OpenCV seja marcada como "Não Respondendo".

---

## 3. Gerenciamento do Ciclo de Vida do Driver PSCam4Win

- O driver reside em `C:\Program Files\PSCam4Win\PSCam4WinTray.exe`.
- O instalador embutido para conveniência do usuário fica em `LegacySensor_Lite/tools/PSCam4Win-Setup.exe`.
- **Detecção:**
  - Verifique instalação testando a existência de `PSCam4WinTray.exe`.
  - Verifique execução inspecionando processos com `tasklist /FI "IMAGENAME eq PSCam4WinTray.exe"`.
  - Inicie o processo com flags de processo desanexado (`subprocess.DETACHED_PROCESS` no Windows) para não bloquear a interface do usuário.
