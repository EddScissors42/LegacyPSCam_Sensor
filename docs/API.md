# 🔌 Especificação da API e Protocolos IPC — Legacy PSCam Sensor

Como o **Legacy PSCam Sensor** opera como um simulador de dispositivo de hardware em tempo real para o jogo **Just Dance PC**, sua API principal consiste no **contrato binário de comunicação entre processos (IPC)** via memória compartilhada do Windows, na **interface da DLL proxy do Kinect** e na **interface de linha de comando (CLI)**.

---

## 1. Interface de Memória Compartilhada (Kinect Shared Memory IPC)

O jogo Just Dance PC lê continuamente as coordenadas do esqueleto humano através de um arquivo mapeado na memória virtual do Windows com nome fixo.

### Metadados da Conexão
- **Identificador (Tag):** `Local\LegacyWebcamKinectPose`
- **Mecanismo:** Windows Paging File Anonymous Mapped Memory (`mmap.mmap(-1, 344, tagname=...)`)
- **Tamanho Total:** Exatamente **344 bytes** (estrito, sem padding adicional)
- **Endianness:** Little-Endian (padrão x86 / x64 do Windows)

---

### Estrutura do Cabeçalho (Header) — 24 Bytes

O cabeçalho possui o formato binário `<IIIIQ`:

| Offset (Bytes) | Campo | Tipo C | Formato Python | Descrição |
|---|---|---|---|---|
| `0x00 - 0x03` | `magic` | `uint32_t` | `<I` | Constante mágica de identificação: `0x3150444A` (`'JDP1'`). |
| `0x04 - 0x07` | `version` | `uint32_t` | `<I` | Versão do protocolo de dados: sempre `1`. |
| `0x08 - 0x0B` | `seq` | `uint32_t` | `<I` | Número de sequência do protocolo seqlock (veja seção 1.2). |
| `0x0C - 0x0F` | `tracked` | `uint32_t` | `<I` | `1` se o jogador estiver detectado e rastreado; `0` se não houver corpo. |
| `0x10 - 0x17` | `timestamp_ms` | `uint64_t` | `<Q` | Timestamp Unix em milissegundos da captura do frame. |

---

### Estrutura dos Joints (20 Articulações) — 320 Bytes

Após o cabeçalho de 24 bytes, seguem-se sequencialmente as 20 articulações corporais do Kinect v1. Cada articulação possui **16 bytes** no formato `<ffff`:

```
Offset 0x18 + (JointIndex * 16):
├── float32 X     (4 bytes) - Coordenada lateral em metros (-1.0 a +1.0)
├── float32 Y     (4 bytes) - Coordenada vertical em metros (-1.0 a +1.0)
├── float32 Z     (4 bytes) - Coordenada de profundidade em metros (~2.0m)
└── float32 Conf  (4 bytes) - Confiança do rastreamento (1.0 = ótimo, 0.0 = perdido)
```

#### Tabela de Índices das 20 Articulações do Kinect v1:
| Índice | Nome do Joint | Descrição Anatômica |
|:---:|---|---|
| **0** | `HipCenter` | Centro da bacia (ponto de origem do esqueleto) |
| **1** | `Spine` | Coluna vertebral (ponto médio entre bacia e ombros) |
| **2** | `ShoulderCenter` | Base do pescoço / centro das clavículas |
| **3** | `Head` | Topo da cabeça / nariz |
| **4** | `ShoulderLeft` | Ombro esquerdo |
| **5** | `ElbowLeft` | Cotovelo esquerdo |
| **6** | `WristLeft` | Pulso esquerdo |
| **7** | `HandLeft` | Extremidade da mão esquerda |
| **8** | `ShoulderRight` | Ombro direito |
| **9** | `ElbowRight` | Cotovelo direito |
| **10** | `WristRight` | Pulso direito |
| **11** | `HandRight` | Extremidade da mão direita |
| **12** | `HipLeft` | Quadril esquerdo |
| **13** | `KneeLeft` | Joelho esquerdo |
| **14** | `AnkleLeft` | Tornozelo esquerdo |
| **15** | `FootLeft` | Ponta do pé esquerdo |
| **16** | `HipRight` | Quadril direito |
| **17** | `KneeRight` | Joelho direito |
| **18** | `AnkleRight` | Tornozelo direito |
| **19** | `FootRight` | Ponta do pé direito |

---

### 1.2 Canais de Imagem e Silhueta (`JMI1` e `JMI2` — 1.305.632 Bytes cada)

O jogo Just Dance PC consome a imagem da câmera e a máscara de profundidade do jogador através de canais de memória mapeada do Windows para compor o HUD da dança e a silhueta ("sombrinha") do jogador no canto inferior da tela e na seleção de dançarinos.

O `Kinect10.dll` implementa suporte duplo e busca primeiro o canal **V2 (`JMI2`)**, retrocedendo para o canal **V1 (`JMI1`)** se V2 não existir. O `LegacyPSCam_Sensor` alimenta ambos simultaneamente:

#### Canal V1: `Local\LegacyWebcamKinectImage` (JMI1)
- **Identificador (Tag):** `Local\LegacyWebcamKinectImage`
- **Tamanho Total:** Exatamente **1.305.632 bytes** (`0x13EC20`)
- **Estrutura do Cabeçalho (32 bytes):** `<IIIIIIQ`
  - `magic` (uint32): `0x31494D4A` (`'JMI1'`)
  - `version` (uint32): `1`
  - `seq` (uint32): Sequência seqlock (ímpar durante escrita, par após conclusão)
  - `tracked` (uint32): `1` se dançarino presente, `0` se ausente
  - `width` (uint32): `640`
  - `height` (uint32): `480`
  - `timestamp_ms` (uint64): Timestamp Unix em milissegundos
- **Payload 1 — Frame BGRA (1.228.800 bytes):**
  - Matriz de 640x480 pixels em formato `BGRA` (4 bytes por pixel), espelhado quando `mirror=True`.
- **Payload 2 — Máscara de Jogador (76.800 bytes):**
  - Matriz de 320x240 pixels em formato `uint8`. **Atenção:** O `Kinect10.dll` testa estritamente `byte >= 0x40` (64 em decimal) para classificar o pixel como Jogador 1. Pixels do corpo utilizam valor **`255`**; fundo contém valor **`0`**.

#### Canal V2: `Local\LegacyWebcamKinectImageV2` (JMI2)
- **Identificador (Tag):** `Local\LegacyWebcamKinectImageV2`
- **Tamanho Total:** Exatamente **1.305.632 bytes** (`0x13EC20`)
- **Estrutura do Cabeçalho (32 bytes):** `<IIIIIIQ`
  - `magic` (uint32): `0x32494D4A` (`'JMI2'`)
  - `version` (uint32): `2`
  - `seq` (uint32): Sequência seqlock
  - `tracked_mask` (uint32): Máscara de bits de jogadores ativos (bit 0 = Jogador 1 ativo)
  - `width` (uint32): `640`
  - `height` (uint32): `480`
  - `timestamp_ms` (uint64): Timestamp Unix em milissegundos
- **Payload 1 — Frame BGRA (1.228.800 bytes):** Idêntico ao canal V1.
- **Payload 2 — Player Index Mask (76.800 bytes):**
  - Matriz de 320x240 pixels em formato `uint8`. Pixels do Jogador 1 contêm valor `1`, pixels do Jogador 2 contêm valor `2` (com resolução de sobreposição pela menor profundidade $Z$), e o fundo contém valor `0`.
- **Cabeçalho `tracked_mask` (uint32):** Máscara de bits dos jogadores ativos (`1` = P1 ativo, `2` = P2 ativo, `3` = P1 e P2 ativos simultaneamente).


---

### 1.3 Canal de Posição do Coach (`Local\LegacyWebcamKinectCoachX` — 28 Bytes)

- **Identificador (Tag):** `Local\LegacyWebcamKinectCoachX`
- **Tamanho Total:** **28 bytes**
- **Estrutura do Cabeçalho:** `<IIIIfQ`
  - `magic` (uint32): `0x3143584A` (`'JXC1'`)
  - `version` (uint32): `1`
  - `seq` (uint32): Sequência seqlock
  - `enabled` (uint32): `1` se ativo, `0` se desligado
  - `coachX` (float32): Coordenada horizontal relativa do coach
  - `timestamp_ms` (uint64): Timestamp Unix em milissegundos

> [!NOTE]
> No modo de rastreamento ao vivo, o campo `enabled` é mantido como `0` (`False`) porque o esqueleto gravado em `JDP1` e `JDP2` já contém o deslocamento lateral $X$ de seleção de dançarino. Ativar `enabled = 1` faria o `Kinect10.dll` somar `coachX` novamente via rotina `0x1020`, duplicando artificialmente o deslocamento lateral do jogador e projetando a cabeça para fora do enquadramento.

---

### Protocolo de Sincronização Seqlock (Lockless)

Para eliminar travamentos e deadlocks entre o Python (produtor dos dados) e o jogo Just Dance (consumidor dos dados), a comunicação utiliza a técnica de **Seqlock**:

1. **Escrita (Python):**
   ```python
   # 1. Torna a sequência ímpar antes de modificar os dados
   seq = (self.seq + 2) | 1
   shared_memory.seek(0)
   shared_memory.write(struct.pack('<IIIIQ', MAGIC, VERSION, seq, tracked, ts_ms))
   
   # 2. Escreve os 320 bytes dos 20 joints em lote único
   shared_memory.write(struct.pack(FULL_JOINTS_FMT, *flat_joints))
   
   # 3. Torna a sequência par após concluir a gravação
   seq += 1
   shared_memory.seek(8)
   shared_memory.write(struct.pack('<I', seq))
   shared_memory.flush()
   ```
2. **Leitura (`Kinect10.dll` no jogo):**
   - O jogo lê o valor de `seq` no offset 8.
   - Se `seq & 1 == 1` (ímpar), significa que o Python está gravando naquele instante. A DLL descarta a leitura e repete.
   - A DLL copia os 320 bytes para um buffer local.
   - A DLL lê novamente o valor de `seq`. Se o valor for idêntico ao lido no início, os dados são 100% consistentes e são repassados ao motor de pontuação do Just Dance.

---

## 2. Emulador de Kinect em Memória e Ponte IPC (`sensor.kinect_emulator`)

O projeto opera através dos canais da Ponte de Memória Compartilhada do Windows (`get_kinect_bridge()`: `JDP1`, `JDP2`, `JMI1`, `JMI2` e `JXC1`) em conjunto com o `KinectEmulatorDaemon`, que injeta em memória RAM a biblioteca proxy de 32 bits `tools/Legacy10.dll` no processo do Just Dance Legacy (`Legacy.exe` / `JustDance.exe`) sem modificar arquivos no disco do jogo.

### 2.1 Sincronização de Timer de Alta Resolução (1 ms) no Python
- O agendador padrão do Windows possui resolução de tick de 15,625 ms, o que pode degradar sleeps de 33 ms (~30 FPS) para 3 ticks (46,875 ms = **21,33 FPS**).
- Ao ativar `winmm.timeBeginPeriod(1)` e `ntdll.NtSetTimerResolution(10000, 1, ...)` no [tracking_session.py](file:///C:/Users/reydn/OneDrive/Documents/Projetos/LegacyPSCam_Sensor/sensor/tracking_session.py), a precisão global do agendador durante a sessão vai para 1,0 ms, garantindo cadência estável de 30/60 FPS sem tocar em binários do jogo.

---

## 3. Interface de Linha de Comando (CLI API)

O arquivo `main.py` aceita os seguintes parâmetros de execução:

```powershell
python main.py [--start] [--mode {pscam,webcam,phone_cam,ds4}] [--camera <int>]
```

### Argumentos:
- `--start`: Pula a exibição da interface gráfica Qt 6 e inicia o rastreamento imediatamente com a última configuração salva.
- `--mode {pscam,webcam,phone_cam,ds4}`: Força o modo de entrada:
  - `pscam`: Seleciona as otimizações para a PlayStation 4 Camera (60 FPS, YUY2/NV12, Stereo Vision padrão).
  - `webcam`: Seleciona as otimizações para webcams convencionais (30/60 FPS DirectShow).
  - `phone_cam`: Seleciona o modo Smartphone Camera via Wi-Fi WebApp (QR Code + TLS/WSS).
  - `ds4`: Inicia o modo de controle sem fio/USB DualShock 4 (IMU 500+ Hz via Virtual Phone).
- `--camera <int>`: Define o índice numérico do dispositivo de vídeo a ser aberto pelo OpenCV (`0`, `1`, etc.).

---

## 4. API Programática dos Módulos Python

Para desenvolvedores que importam os módulos internamente:

### `camera_manager.CameraManager` & `LatestFrameCamera`
- `CameraManager.is_pscam_installed() -> bool`: Retorna se o driver WinUSB da PS4 Camera está instalado/ativo (ou fallback legado).
- `CameraManager.is_pscam_running() -> bool`: Retorna se o backend nativo WinUSB está operacional.
- `CameraManager.initialize_ps4_camera() -> Tuple[bool, str]`: Verifica/instala o pacote INF WinUSB e faz o upload automático do firmware OV580 caso a câmera esteja em modo bootloader (`05A9:0580`).
- `CameraManager.get_windows_camera_names() -> List[str]`: Enumera os nomes amigáveis das câmeras ativas via Win32 `setupapi.dll` (`KSCATEGORY_VIDEO_CAMERA` e `GUID_DEVCLASS_CAMERA` com `DIGCF_PRESENT`) em ~3-5ms in-process (com fallback para WinRT/PowerShell apenas se necessário).
- `CameraManager.enumerate_cameras(max_probe: Optional[int] = None, probe_hardware: bool = False) -> List[CameraInfo]`: Retorna a lista de câmeras conectadas cruzando dispositivos PnP ativos e interfaces WinUSB em ~4ms sem ligar fisicamente o sensor da webcam durante a listagem da UI (`probe_hardware=False`).
- `LatestFrameCamera(camera_index, target_w=640, target_h=480, target_fps=30, mirror=True, is_pscam=False, orientation=0, ps4_eye="right", ps4_backend_mode="native")`: Capturador assíncrono que utiliza `PS4CameraBackend` nativo quando `is_pscam=True`.
- `LatestFrameCamera.set_eye(eye: str)`: Alterna em tempo real entre `"right"` (Olho Direito, padrão) e `"left"` (Olho Esquerdo).
- `LatestFrameCamera.read_left_mono() -> Optional[np.ndarray]`: Retorna o plano de luminância monocromática de 8 bits (H, W) do Olho Esquerdo em <0.08ms diretamente da memória YUY2, eliminando o overhead de conversão YUY2->BGR.
- `LatestFrameCamera.read_left_eye(mono: bool = False) -> Optional[np.ndarray]`: Retorna o frame sincronizado do Olho Esquerdo (com rotação de orientação aplicada). Se `mono=True`, retorna luminância direta sem reconversão BGR.
- `LatestFrameCamera.read_stereo(only_new: bool = False) -> Optional[dict]`: Retorna simultaneamente os frames BGR e YUY2 de ambos os olhos (`right_bgr`, `left_bgr`, `right_yuy2`, `left_yuy2`, `pts`, `timestamp_ms`, `seq`), reutilizando o buffer BGR já convertido do olho ativo.

### `sensor.ps4_backend` — Backend Nativo WinUSB para PlayStation 4 Camera
- `PS4FirmwareManager`:
  - `locate_valid_firmware() -> Optional[bytes]`: Localiza e valida criptograficamente `firmware.bin` (`68.032` bytes, SHA-1 `8b8a6621d358f6782c2e3b31aac2cdfb25102c00`, SHA-256 `09513d10...`) em `%ProgramData%\LegacySensor\Firmware\`.
  - `ensure_firmware(allow_download: bool = True) -> Optional[bytes]`: Garante a presença do firmware validado em disco, baixando via HTTPS caso ausente.
  - `upload_to_bootloader_device(allow_download: bool = True, wait_reenumerate_s: float = 6.0) -> Tuple[bool, str]`: Envia o firmware em blocos de 512B ao dispositivo `05A9:0580`, dispara o comando de reboot (`0x5B`) e aguarda a re-enumeração como `05A9:058B`.
- `PS4UsbDevice`:
  - `probe_hardware_status() -> dict`: Inspeciona o estado PnP e WinUSB da câmera (`READY`, `BOOTLOADER_UPLOADING`, `DRIVER_MISSING`, `DISCONNECTED`).
  - `open(target_w=1280, target_h=800, target_fps=60) -> bool`: Abre as interfaces WinUSB 0 (VideoControl) e 1 (VideoStreaming Alt 1), negocia Probe/Commit UVC YUY2 e ativa Auto-Exposure (`CT_AE_MODE_CONTROL = 0x02`) e Anti-Flicker 60Hz.
- `PS4CameraBackend`:
  - `start() -> bool` / `stop() -> None`: Inicia e encerra o anel isócrono de 8 URBs Overlapped (`WinUsb_ReadIsochPipeAsap`) no endpoint `0x81`.
  - `read_frame(only_new: bool = False) -> Optional[np.ndarray]`: Retorna o frame BGR do olho selecionado (`"right"` por padrão).
  - `read_left_mono() -> Optional[np.ndarray]`: Extrai diretamente em <0.08ms o plano de luminância de 8 bits a partir do buffer `_left_yuy2[:, :, 0]`, com latência zero de conversão de cor.
  - `read_left_frame(mono: bool = False) -> Optional[np.ndarray]`: Retorna o frame do olho esquerdo (luminância uint8 se `mono=True`, ou convertido para BGR).
  - `read_stereo_frames(only_new: bool = False) -> Optional[dict]`: Retorna ambos os fluxos ópticos sincronizados reutilizando o buffer `_selected_bgr` do olho ativo.
- `PS4DriverInstaller`:
  - `has_driver_store_package_fast(use_cache: bool = True) -> bool`: Consulta em ~1.0ms (e ~0.001ms em cache) o `DriverStore\FileRepository` via Win32 `FindFirstFileW` (busca prefixada B-tree no NTFS) sem invocar `pnputil.exe`.
  - `invalidate_cache() -> None`: Invalida o cache em memória do DriverStore e de pacotes `oemXX.inf` publicados.
  - `verify_driver_status() -> dict`: Verifica sem elevação UAC se `legacy_pscam_device.inf` está instalado e associado ao `WinUSB.sys` (incluindo disponibilidade do instalador de fallback assinado `fallback_installer_present`).
  - `get_fallback_installer_path() -> Optional[Path]`: Localiza o instalador assinado de fallback `tools/PSCam4Win-Setup.exe`.
  - `install_or_repair_driver(force_reinstall: bool = False, allow_fallback_installer: bool = True) -> Tuple[bool, str]`: Solicita elevação pontual via `pnputil.exe` apenas quando necessário e aciona automaticamente o instalador de fallback caso a política de assinatura digital do Windows rejeite um catálogo INF não assinado.

### `sensor.gesture_detector` — Reconhecimento de Gestos Corporais
- `check_arm_raised(px_joints) -> bool`: Avalia os 20 joints 2D do jogador (`px_joints`), retornando `True` caso o pulso e a mão esquerda ou direita estejam confortavelmente elevados acima do nível da cabeça ou ombros.
- `dispatch_enter_keystroke() -> None`: Dispara de forma assíncrona (thread desacoplada) o evento físico de teclado `VK_RETURN` (`0x0D`, scan code `0x1C`) para o processo do Just Dance PC via `ctypes.windll.user32.keybd_event`.
- `ArmRaiseGestureDetector(enabled=True, hold_seconds=2.0, cooldown_seconds=2.5)`:
  - `update(px_joints, is_tracked, vphone=None, now=None) -> dict`: Gerencia a máquina de estados do gesto, calcula o progresso percentual acumulado durante a sustentação da pose, aciona o envio de `Enter` e `VALID` do Celular Virtual ao completar o tempo estipulado (`hold_seconds`), e gerencia o período de cooldown para evitar disparos repetitivos.

### `pose_tracker.PoseTracker`
- `PoseTracker(model_path=None, detection_confidence=0.5, smoothing_alpha=0.55, target_height_m=1.75, cfg=None, model_variant=None)`: Construtor do motor de IA (`model_variant` aceita `"lite"` ou `"full"`, com fallback automático de `"heavy"` legado para `"full"`).
- `PoseTracker.process_frame(frame: np.ndarray, mirror: bool = False) -> Tuple[bool, List[Tuple], List[Tuple], Optional[np.ndarray]]`: Processa o quadro bruto, executa Hand Anchor, suavização EMA, calibração de esqueleto e gera a máscara de segmentação anatômica. Retorna `(sucesso, kinect_joints, pixel_joints, body_mask)`.
- `PoseTracker.build_body_mask(norm_landmarks, width, height) -> np.ndarray`: Gera a máscara binária 2D do corpo do jogador a partir dos landmarks.
- `PoseTracker.reset_filters()`: Limpa o estado interno dos filtros de suavização após perda de rastreamento.

### `kinect_shared_memory.KinectBridge`
- `KinectBridge()`: Inicializa e unifica os três canais IPC (`Local\LegacyWebcamKinectPose`, `Local\LegacyWebcamKinectImage` e `Local\LegacyWebcamKinectCoachX`).
- `KinectBridge.write(joints, frame_bgr, mask_binary, tracked=True) -> bool`: Grava atomicamente as articulações no canal `JDP1` e o frame BGRA + máscara de profundidade no canal `JMI1`.
- `KinectBridge.write_empty() -> bool`: Notifica o jogo de que não há jogador rastreado.
- `KinectBridge.close()`: Fecha e desaloca todos os blocos de memória mapeada com segurança.

### `kinect_shared_memory.KinectSharedMemory`
- `KinectSharedMemory(tagname: str = "Local\\LegacyWebcamKinectPose")`: Inicializa o buffer de pose de 344 bytes.
- `KinectSharedMemory.write_pose(joints, tracked: bool = True)`: Grava as 20 articulações no formato binário `<IIIIQ` + `<ffff` * 20.

### `kinect_shared_memory.KinectImageSharedMemory`
- `KinectImageSharedMemory(tagname: str = "Local\\LegacyWebcamKinectImage")`: Inicializa o buffer de imagem de 1.305.632 bytes.
- `KinectImageSharedMemory.write_image_and_mask(frame_bgr, mask_binary, tracked: bool = True)`: Converte e grava o frame BGRA 640x480 e a máscara de profundidade 320x240 para o HUD do jogo.

---

## 5. Esquema de Configuração (`config.json`)

As preferências do usuário são persistidas em `config.json` via `ConfigManager`:

```json
{
  "camera_mode": "pscam",
  "camera_index": 0,
  "ps4_camera_backend": "native",
  "ps4_eye": "right",
  "pscam_preset": "1280x800 @ 60 FPS",
  "webcam_preset": "640x480 @ 30 FPS",
  "mirror_horizontal": true,
  "tracking_preset": "balanced",
  "pose_model": "full",
  "smoothing_alpha": 0.55,
  "detection_confidence": 0.5,
  "target_height_m": 1.75,
  "auto_calibrate": true,
  "launch_pscam_tray": true,
  "show_hud": true
}
```

- `ps4_camera_backend`: Backend de captura para a PlayStation 4 Camera (`"native"` para WinUSB direto, `"pscam4win"` para fallback legado).
- `ps4_eye`: Sensor óptico ativo da PlayStation 4 Camera (`"right"` como padrão para o Olho Direito, `"left"` para o Olho Esquerdo).
- `tracking_preset`: Perfil ativo selecionado no menu (`"balanced"`, `"competitive"`, `"stable"` ou `"custom"`).
- `smoothing_alpha`: Coeficiente de suavização EMA (0.20 a 0.85).
- `detection_confidence`: Limiar mínimo de confiança da IA MediaPipe (0.30 a 0.80).
- `target_height_m`: Escala métrica alvo interna (1.75m) mantida constante pelo `SkeletonCalibrator`.

---

## 6. Interface de Linha de Comando (CLI)

O ponto de entrada `main.py` aceita argumentos de linha de comando para controle direto:

```powershell
python main.py [-h] [--start] [--mode {pscam,webcam,phone_cam,ds4}] [--camera CAMERA]
```

| Argumento | Opções | Padrão | Descrição |
|---|---|---|---|
| `--start` | Flag booleana | `False` | Inicia a sessão de rastreamento diretamente sem abrir a interface gráfica. |
| `--mode` | `pscam`, `webcam`, `phone_cam`, `ds4` | Configurado em `config.json` | Força o modo de sensor/controle a ser utilizado. |
| `--camera` | Inteiro (`0`, `1`, ...) | Configurado em `config.json` | Força o índice da câmera de captura no OpenCV. |

---

## 7. Pacote de Interface Gráfica (`ui`)

O pacote `ui` expõe uma interface modular baseada exclusivamente em **PySide6 (Qt 6)**:

- `ui.launch_app() -> int`: Inicializador principal da interface gráfica Qt 6 (`PySide6`).
- `ui.LegacySensorQtGUI`: Janela principal baseada em PySide6 / Qt 6, com detecção de hotplug por sinais Qt e balão contextual de estado de hardware.
- `ui.LegacySensorGUI`: Alias padrão para `LegacySensorQtGUI`.
- `ui.pages`: Exporta `UIPagesMixin` com os construtores declarativos das 4 páginas (`_build_video_view`, `_build_calib_view`, `_build_exp_view`, `_build_ds4_view`).
- `ui.widgets`: Exporta `pil_to_qpixmap`, `SlidingStackedWidget`, `DeviceNavCard` e `CalibPresetCard`.
- `ui.benchmark_dialog`: Exporta `TelemetryBenchmarkChart` e `TelemetryBenchmarkDialog`.
- `ui.HAS_QT -> bool`: Booleano que indica se o PySide6 está instalado e operacional.

---

## 8. Driver Bluetooth/USB HID do DualShock 4 e Compatíveis (`sensor.ds4_controller`)

Módulo nativo Windows HID (zero dependências) para leitura de alta taxa (500+ Hz) do controle DualShock 4 e gamepads compatíveis (Nível A) via Bluetooth ou cabo USB.

### Constantes e Estruturas de Descoberta
- `KNOWN_DS4_TARGETS: Dict[str, Tuple[str, ...]]`: Mapeamento de VIDs e PIDs conhecidos:
  - Sony (`054c`): `05c4` (V1), `09cc` (V2), `0ba0` (Dongle USB sem fio).
  - Hori (`0f0d`): `005e`, `0066`, `00ee`, `011c`.
  - Nacon (`146b`): `06cd`, `06e5`, `0d01`, `0d02`.
  - Razer (`1532`): `1000`, `1004`, `1007`, `1008`, `1009`, `100a` (Raiju Ultimate/Tournament).
  - Astro (`9886`): `0025` (C40 TR).
  - Scuf (`2e95`): `7725`, `9925` (Vantage / Impact).
  - Qanba (`2c22`): `2000`, `2300`, `2500`.
  - Mad Catz (`0738`): `5252`, `8250`, `8384`.
  - ShanWan (`2563`): `0575`, `0555`, `0523` (clones sem fio).
  - DragonRise (`0079`): `181b`, `181c`, `181d` (clones sem fio).
- `BLACKLISTED_DEVICE_VENDORS = ("045e",)`: Dispositivos explicitamente bloqueados (controles Microsoft Xbox sem giroscópio/acelerômetro).

### Funções e Classes Principais
- `find_ds4_devices(permissive: bool = True) -> List[str]`: Enumera as interfaces HID PnP do Windows sob a GUID `{4d1e55b2-f16f-11cf-88cb-001111000030}`. No modo estrito filtra por Sony (`0x054C`), e no modo permissivo aceita os alvos conhecidos e qualquer controle HID compatível (exceto Xbox).
- `is_compatible_ds4_path(path: str, permissive: bool = True) -> bool`: Valida se o caminho HID pertence a um dispositivo compatível.
- `detect_controller_name(path: str) -> str`: Identifica e retorna o nome amigável do modelo (ex.: `"Razer Raiju (PS4)"`, `"ShanWan DS4 Clone"` ou `"Generic / Clone DS4"`).
- `get_ds4_controller() -> DS4Controller`: Retorna a instância singleton do controlador.
- `DS4Controller.connect(device_path=None, permissive=None) -> bool`: Abre o handle Win32, realiza o handshake do Relatório Estendido 0x11 (se aplicável), detecta o nome do periférico, aciona vibração háptica de boas-vindas e inicia a thread de amostragem.
- `DS4Controller.disconnect() -> None`: Desativa a barra de luz e fecha o handle Win32 de forma segura.
- `DS4Controller.trigger_rumble(small, large, duration_sec) -> None`: Dispara um pulso háptico assíncrono.
- `DS4Controller.set_lightbar(r, g, b) -> None`: Altera a cor RGB da barra de luz LED.
- `DS4State`: Dataclass contendo:
  - `connected: bool`
  - `is_usb: bool`
  - `battery_pct: int`
  - `is_charging: bool`
  - `accel_g: Tuple[float, float, float]`
  - `gyro: Tuple[float, float, float]`
  - `buttons: Dict[str, bool]`
  - `sample_rate_hz: float`
  - `imu_frozen: bool`: Flag booleana que acusa quando a magnitude do acelerômetro é $< 0.05G$ por 50 leituras seguidas (sensor ausente ou sem envio pelo Bluetooth).
  - `controller_name: str`: Nome legível do controle conectado.

### Estrutura do Pacote Bluetooth Output Report 0x11 (78 Bytes)
- **Byte 0:** `0x11` (Report ID)
- **Byte 1:** `0xC0` (Streaming & flags)
- **Byte 3:** `0x07` (Habilita motores de rumble e LED lightbar)
- **Byte 6:** Motor pequeno de alta frequência (0..255)
- **Byte 7:** Motor grande de baixa frequência (0..255)
- **Bytes 8–10:** RGB da barra de luz LED
- **Bytes 74–77:** Checksum CRC-32 (IEEE 802.3) little-endian calculado sobre `bytes([0xA2]) + out_rep[0:74]`.

---

## 9. Celular Virtual e Auto-Detecção de Músicas (`sensor.virtual_phone`)

O módulo `sensor.virtual_phone` gerencia a comunicação com o Just Dance através do protocolo WebSocket `/smartphone` (v1/v2):

### Funções de Auto-Detecção de Processo e Música Ativa
- `find_just_dance_pids() -> List[int]`: Enumera os processos em execução via `CreateToolhelp32Snapshot` Win32 buscando instâncias de `jd2022.exe`, `jd2021.exe`, `jd2020.exe`, `jd2019.exe`, `jd2018.exe`, `jd2017.exe`, `justdance.exe` (latência ~0.5ms).
- `detect_active_song_from_game_process() -> str`: Varre páginas de dados privadas (`MEM_COMMIT`, ignorando `MEM_IMAGE` e páginas executáveis) do processo Just Dance com um buffer reutilizável pré-alocado de 1 MB para localizar a stream ativa `/map/<MapName>/...webm`. Converte o identificador do mapa (ex: `SmalltownBoy`) no título formatado da música (`Smalltown Boy`).
- `VirtualPhoneController.current_song`: Propriedade que retorna o nome da música ativa, executando a busca em memória sob demanda apenas quando a gravação de telemetria ou benchmark automático estiverem ativos (`auto_record_enabled` ou `_logging_enabled`), com intervalo mínimo de 2.5s.

### `sensor.virtual_phone.HandAccelerometer`
- `HandAccelerometer(hand="right", sensitivity=1.0)`: Converte as 20 articulacoes do Kinect em aceleracao 3D [ax, ay, az] compativel com o protocolo de pontuacao de smartphone do Just Dance.
  - **Filtro de Velocidade Pre-Derivada:** Filtro exponencial com tau = 45ms para supressao de ruido de segunda ordem.
  - **Escala de Forca G Calibrada:** Ganho calibrado contra ground truth de controle fisico DualShock 4 (Smalltown Boy).
  - **Teto Vetorial 3D:** Clamping de magnitude Euclidiana a 7.0G maximo.
  - **Convencao de Eixos:** Screen-relative (+Y ao longo do antebraco, +Z em direcao ao dancarino).

---

## 10. Motor de Visão Estéreo (`sensor.stereo_matcher`)

O pacote `sensor.stereo_matcher` implementa o pipeline óptico de visão estéreo para a PlayStation 4 Camera (sensores dual OV9713 e ponte OV580):

### 10.1 Constantes Ópticas
- `PS4_STEREO_BASELINE_M = 0.0852`: Distância física entre centros ópticos (85.2 mm).
- `NOMINAL_FOCAL_AT_1280 = 860.0`: Distância focal de referência em pixels a 1280x800 (HFOV ~73°).
- `STEREO_MODES`: `("disabled", "sparse_metric", "full_depth")`.

### 10.2 Classes Principais
- `StereoCalibrator(baseline_m=0.0852)`:
  - `update_resolution(w, h)`: Computa matrizes intrínsecas $K_1, K_2$, rotação $R$, translação $T = [B, 0, 0]^T$ e look-up tables `cv2.initUndistortRectifyMap`.
  - `rectify(left, right, force_remap=False) -> (rect_left, rect_right)`: Em geometria rígida de fábrica sem distorção (`is_identity=True`), retorna os frames diretamente em $<0.001\text{ ms}$ (zero-copy), eliminando remapeamento bilinear redundante. Quando calibração customizada estiver presente ou `force_remap=True`, executa `cv2.remap` em $<0.8\text{ ms}$.
- `StereoDepthEngine(baseline_m=0.0852)`:
  - `triangulate_sparse_joints(rect_left, rect_right, joints_2d, search_radius_px=48, patch_half_size=6, vertical_tol_px=4) -> Dict[joint_id, (X, Y, Z, conf)]`:
    Executa busca em banda epipolar 2D no canal verde (`cv2.matchTemplate` com interpolação parabólica 2D) seguida de refinamento sub-pixel por Fluxo Óptico Piramidal Lucas-Kanade (`cv2.calcOpticalFlowPyrLK` em ROIs locais) em $<0.8\text{ ms}$, computando profundidade métrica $Z = \frac{f \cdot B}{d}$ e auto-calibrando dinamicamente o desalinhamento vertical entre as lentes (`vertical_offset_px`).
  - `compute_dense_depth_mask(rect_left, rect_right, target_w=320, target_h=240, min_z_m=0.8, max_z_m=2.8, align_to_right=True) -> np.ndarray`:
    Calcula mapa de disparidade a 320x200 via `cv2.StereoSGBM_3WAY` (~2.5ms), gerando máscara binária uint8 (255 = zona do jogador, 0 = fundo/fora).
  - `compute_confirmed_background_mask(rect_left, rect_right, target_w=320, target_h=240, min_z_m=0.8, max_z_m=2.8, align_to_right=True) -> np.ndarray`:
    Identifica regiões positivamente confirmadas fora do envelope de profundidade do dançarino ($Z > \text{max\_z\_m}$ ou $Z < \text{min\_z\_m}$), alinhadas à lente direita.

---

## 11. Emulador de Kinect em Memória (`sensor.kinect_emulator`)

O módulo `sensor.kinect_emulator` emula o sensor Kinect diretamente na memória RAM do Just Dance Legacy (32-bit, modo *Zero-File-Replacement* com `tools/Legacy10.dll`, integrado à Ponte de Memória Compartilhada), sem exigir a substituição ou alteração de qualquer arquivo no disco do jogo:

- `KINECT_ORDINALS_ORDER = [16, 5, 6, 21, 22, 9, 17, 26]`: Ordem dos 8 ordinais da API NUI mapeados na tabela IAT do `Legacy.exe` (32-bit).
- `TARGET_PROCESS_NAMES = ["legacy.exe", "justdance.exe"]`: Executáveis 32-bit monitorados pelo daemon.
- `KinectEmulatorDaemon(cfg=None)`:
  - `start() -> None` / `stop() -> None`: Inicia e encerra a thread daemon de monitoramento de processos (`KinectEmulatorDaemon`).
  - `get_status() -> Dict[str, Any]`: Retorna o estado atual (`enabled`, `running`, `connected`, `game_name`, `pid`, `mode` `"iat_hook_32"`).
  - `register_status_callback(cb: Callable[[bool, str, int], None]) -> None`: Registra callback acionado ao conectar ou desconectar do processo do jogo.
  - `_scan_for_game_process() -> Optional[Dict[str, Any]]`: Varre processos ativos em $<0.5\text{ ms}$ via snapshot de kernel `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)`.
  - `_is_target_32bit(pid: int) -> bool`: Verifica via `IsWow64Process` se o processo alvo é 32-bit (WoW64 / PE32).
  - `_log_diag_once(pid, reason_key, message)`: Registra diagnósticos de injeção sem spam (incluindo detecção de `ERROR_ACCESS_DENIED (5)` quando o jogo roda como Administrador).

---

## 12. Subsistema de Logging & Telemetria de Dança (`sensor.session_logger`)

O módulo `sensor.session_logger` gerencia o ciclo de vida dos arquivos de diagnóstico e a gravação assíncrona da telemetria de dança:

### 12.1 Arquivos e Política de Retenção
- `logs/session.log`: Log textual formatado (`YYYY-MM-DD HH:MM:SS.mmm [LEVEL] [CATEGORY] message`) contendo cabeçalho do sistema, descoberta de câmeras e controles, status da memória compartilhada, injeção do emulador e stack traces de falhas.
- `logs/session_previous.log`: Backup preservado da execução anterior no momento da abertura do programa.
- `logs/session_telemetry.csv`: Streaming tabular de alta frequência das variáveis de movimento durante o rastreamento ativo.
- `logs/session_telemetry_previous.csv`: Backup da telemetria da sessão anterior.

### 12.2 Especificação do Esquema CSV (`session_telemetry.csv`)
O arquivo CSV de telemetria possui cabeçalho de 25 colunas:

| Coluna | Tipo | Descrição |
|---|---|---|
| `timestamp_ms` | `uint64` | Timestamp Unix em milissegundos da amostra. |
| `rel_time_s` | `float32` | Tempo decorrido em segundos a partir do `START TRACKING`. |
| `source` | `string` | Origem do rastreamento (`"camera"` ou `"ds4"`). |
| `song_name` | `string` | Nome da música ativa detectada pelo jogo ou `"DanceSession"`. |
| `coach_id` | `int32` | Índice base zero do dançarino ativo selecionado (`0` a `3`). |
| `is_tracked` | `uint32` | `1` se o corpo ou controle estiver rastreado; `0` se perdido. |
| `ax, ay, az` | `float32` | Aceleração 3D calibrada em forças G. |
| `mag_g` | `float32` | Magnitude vetorial tridimensional: $\sqrt{a_x^2 + a_y^2 + a_z^2}$. |
| `speed_mps` | `float32` | Velocidade escalar da mão de pontuação em metros por segundo. |
| `hand_x, hand_y, hand_z` | `float32` | Coordenadas espaciais métricas da mão no espaço do sensor. |
| `shoulder_r_x/y/z` | `float32` | Coordenadas 3D do ombro direito. |
| `elbow_r_x/y/z` | `float32` | Coordenadas 3D do cotovelo direito. |
| `wrist_r_x/y/z` | `float32` | Coordenadas 3D do pulso direito. |
| `joints_tracked_count` | `int32` | Quantidade de articulações com confiança $> 0.3$ (de 0 a 20). |
| `cam_fps` | `float32` | Taxa real de quadros da câmera ou taxa de polling Hz do DualShock 4. |
| `infer_fps` | `float32` | Taxa de inferência do MediaPipe Pose Landmarker. |
| `game_feedback` | `string` | Classificação do movimento enviada pelo jogo (*PERFECT*, *SUPER*, *GOOD*, etc.). |
| `controller_btn` | `string` | Último evento de botão físico acionado (`"L1:press"`, `"R1:press"`, etc.). |

### 12.3 API Pública (`SessionLogger`)
- `initialize(wipe_old_logs=True, backup_previous=True) -> None`: Prepara diretórios, rotaciona logs anteriores e inicia o consumidor assíncrono.
- `log_system_environment() -> None`: Registra versão do Windows, CPU, RAM (Win32 API) e runtime Python.
- `map_active_controller(controller_type: str, name: str, details: str = "") -> None`: Atualiza e registra o controle mapeado para a dança.
- `start_telemetry_tracking(source, song_name, coach_id, config_summary) -> None`: Abre e inicia o streaming do arquivo CSV no `START TRACKING`.
- `record_telemetry_sample(...) -> None`: Enfileira amostras de forma não-bloqueante na thread em segundo plano.
- `stop_telemetry_tracking(summary_metrics: Optional[Dict[str, Any]] = None) -> None`: Esvazia a fila pendente e grava resumo da sessão no `session.log`.
- `install_exception_hooks() -> None`: Registra hooks de crash em `sys.excepthook` e `threading.excepthook`.

---

## 13. Subsistema Modular Person Lock-In (`sensor.person_lock`)

O módulo `sensor.person_lock` fornece persistência cinemática e travamento de identidade do dançarino a 60 FPS, com chaves modulares individuais para ativação/desativação em tempo real:

### 13.1 Classes Principais
- `InertialCoastingFilter(cfg=None)`:
  - `is_enabled -> bool`: Verifica `person_lock_enabled` e `inertial_coasting_enabled`.
  - `set_enabled(enabled: bool) -> None`: Ativa ou desativa a predição inercial em tempo real.
  - `record_valid_frame(joints_3d, joints_2d, body_mask, norm_landmarks=None, dt=None) -> (joints_3d, joints_2d, body_mask)`: Atualiza velocidades 3D/2D amortecidas e aplica *re-entry LERP blend* por 3 frames após micro-quedas.
  - `coast(dt=None, frame_w=640, frame_h=480) -> (is_coasting, coasted_3d, coasted_2d, coasted_mask)`: Extrapola o esqueleto 3D/2D e translada a máscara `320x240` durante perdas de detecção de até `inertial_coasting_max_ms` (`250 ms`).
- `DancerIdentityLock(cfg=None)`:
  - `is_enabled -> bool` / `is_roi_focus_enabled -> bool`: Verifica `person_lock_enabled`, `dancer_lock_enabled` e `dancer_lock_roi_focus`.
  - `validate_candidate(frame_bgr, norm_landmarks, dt=None) -> bool`: Extrai o histograma HSV 12x8 do tronco e valida a continuidade espacial/escala em $<0.05\text{ ms}$, rejeitando falsos positivos de fundo ou transeuntes.
  - `apply_roi_focus(infer_rgb) -> np.ndarray`: Atenua bordas periféricas distantes da envergadura ativa do dançarino no buffer privado de inferência.
- `PersonLockController(cfg=None)`:
  - Fachada unificada que coordena `InertialCoastingFilter` e `DancerIdentityLock` dentro do `PoseTracker`.
