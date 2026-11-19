# 🛠️ Guia de Instalação e Configuração — Legacy PSCam Sensor

Este documento apresenta o passo a passo completo para preparar o ambiente, instalar dependências, configurar o driver da **PlayStation 4 Camera**, vincular a DLL ao jogo **Just Dance PC** e executar a aplicação.

---

## 📋 Pré-Requisitos do Sistema

- **Sistema Operacional:** Windows 10 ou Windows 11 (64-bit).
- **Python:** Python 3.10 ou superior (recomendado Python 3.12 ou 3.15 de 64-bit).
- **Portas USB:**
  - Para Webcams comuns: Porta USB 2.0 ou superior.
  - Para **PlayStation 4 Camera:** **Porta USB 3.0 (azul) obrigatória**, pois o sensor duplo da PS4 Camera requer a largura de banda total do USB 3.0 para alimentar o stream de 60 FPS.
- **Espaço em Disco:** Menos de 150 MB (contra os 632 MB da versão original).

---

## 1. Instalação das Dependências Python

Abra o prompt de comando (PowerShell ou CMD) na pasta do projeto e execute:

```powershell
python -m pip install -r requirements.txt
```
*(Ou manualmente: `python -m pip install opencv-python mediapipe numpy Pillow PySide6`)*

> [!NOTE]
> O pacote `PySide6` provê a interface gráfica de alta performance baseada em Qt 6 com transições animadas inspiradas no console PlayStation 5.

---

## 2. Configuração da PlayStation 4 Camera (PS4 Camera — Backend Nativo WinUSB)

A PlayStation 4 Camera (modelos CUH-ZEY1 e **PlayStation 4 Camera Slim** CUH-ZEY2 com adaptador USB 3.0) é gerenciada diretamente pelo **Backend Nativo WinUSB** integrado ao `LegacyPSCam_Sensor`, sem necessidade do aplicativo externo `PSCam4Win`.

### Passo 2.1 — Conectar a Câmera
1. Conecte a PS4 Camera em uma porta **USB 3.0** nativa do computador.
2. Ao ser conectada fisicamente, a câmera inicia em seu modo de bootloader volátil (`USB\VID_05A9&PID_0580`).

### Passo 2.2 — Associação Automática ao WinUSB (`legacy_pscam_device.inf` & Fallback Assinado)
1. Ao abrir o **Legacy PSCam Sensor**, o módulo `PS4DriverInstaller` verifica automaticamente se o driver de sistema `WinUSB.sys` da Microsoft já está associado às interfaces da câmera (`VID_05A9&PID_0580` e `VID_05A9&PID_058B&MI_00`).
2. Caso o pacote INF ainda não esteja registrado no repositório de drivers do Windows, clique no botão de inicialização na interface. Uma única confirmação UAC será solicitada para registrar `driver/legacy_pscam_device.inf` via `pnputil.exe`.
3. **Fallback Automático Assinado:** Em instalações do Windows 10/11 onde a política de *Driver Signature Enforcement* exija um catálogo `.cat` assinado e rejeite o registro via `pnputil`, o `PS4DriverInstaller` aciona automaticamente o instalador assinado de fallback `tools/PSCam4Win-Setup.exe` (quando presente).
4. Nas execuções seguintes, nenhuma elevação UAC é solicitada.

### Passo 2.3 — Gerenciamento Automático de Firmware OV580 (Online e Offline)
- O controlador OV580 armazena seu firmware em memória RAM volátil, exigindo o envio do `firmware.bin` (`68.032` bytes, SHA-1 `8b8a6621d358f6782c2e3b31aac2cdfb25102c00`) a cada reconexão física.
- **Modo Online (Automático):** Se o arquivo não estiver presente em `%ProgramData%\LegacySensor\Firmware\firmware.bin`, o `PS4FirmwareManager` baixa automaticamente a versão final verificada, valida seus hashes SHA-1 e SHA-256 em memória e a armazena em `%ProgramData%\LegacySensor\Firmware\`.
- **Modo Offline (Manual):** Para computadores sem acesso à internet, basta copiar o arquivo `firmware.bin` válido (68.032 bytes) para `%ProgramData%\LegacySensor\Firmware\firmware.bin` ou `<PastaDoApp>\Firmware\firmware.bin`.
- Assim que o firmware é enviado, a câmera reinicializa automaticamente (~1,5s) como `USB Camera-OV580` (`VID_05A9&PID_058B`) e inicia a captura em **1280x800 @ 60 FPS** utilizando o **Olho Direito** por padrão (com opção de alternar para o **Olho Esquerdo** na interface).

---

## 3. Configuração do Just Dance PC (Kinect Bridge)

Para que o jogo Just Dance PC consiga ler os movimentos gerados pelo simulador:

1. Localize a pasta `tools/` dentro de `LegacyPSCam_Sensor/`.
2. Copie o arquivo **`Kinect10.dll`**.
3. Abra a pasta raiz da sua instalação do **Just Dance PC** (onde fica o executável do jogo, por exemplo `JustDance.exe` ou a pasta do Legacy Offline).
4. Cole o `Kinect10.dll` na pasta do jogo, substituindo o existente se solicitado.

> [!TIP]
> Dentro do menu do Legacy PSCam Sensor há um atalho conveniente: clique no botão **"📁 Abrir Pasta do Kinect10.dll"** para abrir a pasta de origem imediatamente no Windows Explorer.

---

## 4. Executando a Aplicação

Dê um duplo-clique no executável nativo do projeto:
```cmd
LegacySensor.exe
```
*(ou se preferir, execute `INICIAR_SENSOR.bat`)*

- Abre o menu visual escuro instantaneamente, sem nenhuma janela de console/terminal.
- Permite alternar entre **PlayStation Camera** e **Webcam Padrão**.
- Permite escolher a resolução e taxa de quadros (ex: `1280x800 @ 60 FPS`).
- Ajusta a sensibilidade do rastreador e calibração de altura.
- Clique em **`▶ INICIAR RASTREAMENTO`** para iniciar a captura.

### Linha de Comando (CLI Avançada)
Você também pode iniciar via terminal passando parâmetros específicos:

```powershell
# Iniciar com a PS4 Camera no preset padrão
python main.py --mode pscam

# Iniciar forçando o uso de uma webcam específica (ex: índice 0)
python main.py --mode webcam --camera 0
```

---

## 5. Permissões de Usuário e Inicialização do Driver (Sem Modo Administrador)

Por padrão, o executável do driver PSCam4Win (`PSCam4WinTray.exe`) possui uma flag interna em seu manifesto exigindo privilégios de Administrador. Se o **Legacy PSCam Sensor** for aberto como usuário padrão (sem "Executar como Administrador"), o Windows anteriormente retornava o erro `[WinError 740] A operação solicitada requer elevação`.

### Soluções e Workarounds Nativos:
1. **Camada de Compatibilidade Automática (`RunAsInvoker` — Padrão do Sensor):**
   - O código do Legacy PSCam injeta automaticamente `__COMPAT_LAYER = 'RunAsInvoker'` ao disparar o driver. O Windows ignora a exigência de elevação do manifesto e inicializa o PSCam4Win com as credenciais do seu usuário normal, **sem necessidade de rodar o Legacy PSCam como administrador e sem janelas do UAC**.
2. **Fallback com ShellExecute (`runas`):**
   - Se o sistema bloquear a injeção de compatibilidade por diretiva, o sensor recorre à API `ShellExecuteW("runas")`, que solicita a confirmação do UAC **exclusivamente para o driver**, mantendo o Legacy PSCam sem privilégios elevados.
3. **Workaround Silencioso (Agendador de Tarefas do Windows):**
   - Para inicialização 100% silenciosa com privilégios elevados permanentes, você pode criar uma tarefa no Agendador do Windows com o nome `PSCam4Win` marcada com *"Executar com privilégios mais altos"*. Qualquer processo pode acioná-la via `schtasks /run /tn "PSCam4Win"`.
4. **Iniciar com o Windows (Recomendado):**
   - Configure o PSCam4Win para iniciar junto com o Windows (na pasta `shell:startup` ou Registro de inicialização). Dessa forma, o driver já estará pronto na bandeja do sistema sempre que você abrir o Legacy PSCam Sensor.

---

## 5. Pareamento e Uso do DualShock 4 e Controles Compatíveis (Bluetooth / USB)

Para utilizar o controle DualShock 4 ou controles compatíveis (Nível A) como controle de mão (rastreando os movimentos pelo acelerômetro físico interno):

1. **Colocar o Controle em Modo de Pareamento (ou conectar via USB):**
   - **DualShock 4:** Com o controle desligado, mantenha pressionados os botões **Share** e **PS** simultaneamente por 3 a 5 segundos até que a barra de luz comece a piscar rapidamente em branco.
   - **Controles de Terceiros Licenciados (Hori, Nacon, Razer Raiju, Astro C40, Scuf, Qanba):** Siga as instruções do fabricante para pareamento Bluetooth no PC ou conecte o cabo USB / dongle sem fio correspondente.
   - **Réplicas / Clones Genéricos (ShanWan, DragonRise):** Podem ser pareados via Bluetooth ou plugados diretamente via cabo USB.
2. **Conectar no Windows:**
   - Acesse **Configurações do Windows > Bluetooth e Dispositivos > Adicionar Dispositivo > Bluetooth**.
   - Selecione o dispositivo (geralmente listado como **Wireless Controller**). O Windows concluirá o pareamento e registrará o dispositivo HID.
3. **No Legacy PSCam Sensor:**
   - Na barra lateral em `CAPTURE DEVICE`, clique em **DualShock 4**.
   - O sistema reconhece o modelo automaticamente (ex.: *"Sony DualShock 4"*, *"Razer Raiju (PS4)"*, *"ShanWan DS4 Clone"* ou *"Generic / Clone DS4"*).
   - O **Modo Permissivo** (`Permissive Discovery Mode`) vem ativado por padrão para aceitar controles de terceiros e clones.
   - **Aviso de IMU Travado (`[!] IMU SENSOR FROZEN 0G`):** Se o seu controle for uma réplica genérica que conecta no Windows via Bluetooth mas não transmite os dados de movimento pelo ar (gerando 0G contínuo em vez de ~1.0G de gravidade em repouso), a interface exibirá um alerta em vermelho. **Basta conectar o controle pelo cabo USB** para que o stream de aceleração física funcione normalmente.
   - Na aba **Controller Settings**, você verá o status em tempo real (`Status: Connected • 500 Hz • Battery: X%`), a leitura contínua do acelerômetro 3D e poderá testar a vibração clicando em **Test Rumble Vibration**.
   - Clique em **START CONTROLLER (DS4)** para iniciar a sessão de dança!

---

## 6. Como Jogar no Just Dance PC

1. Com o rastreador ativo (janela com esqueleto e contadores de FPS visível), abra o **Just Dance PC**.
2. Na tela de seleção de controle do jogo, escolha a opção **Kinect Sensor**.
3. O jogo detectará imediatamente o simulador através da memória compartilhada `Local\LegacyWebcamKinectPose`.
4. Posicione-se em frente à câmera a uma distância de aproximadamente **1,8 a 2,5 metros** para que todo o seu corpo (da cabeça aos tornozelos) fique visível.
5. Selecione sua música e dance! O esqueleto responderá a cada movimento e pontuará no jogo.
