/*
 * LegacyMove.dll (32-bit) / LegacyMove_x64.dll (64-bit)
 * In-Memory Virtual PlayStation Move (ZCM2 — VID 0x054C / PID 0x0C5E) HID Proxy
 * for Just Dance PC (Legacy.exe x86, Legacy Lab.exe x64, LegacyLab_Offline.exe x64).
 *
 * Bridges Legacy PSCam Sensor's lockless seqlock shared memory channel:
 *   - Local\LegacyPSMoveState (128 bytes, magic 'PSM1')
 *
 * How it works:
 *   1. Patches the host game's PE Import Address Table (IAT) purely in RAM for:
 *      - SETUPAPI.dll: SetupDiGetClassDevsW, SetupDiEnumDeviceInterfaces,
 *                      SetupDiGetDeviceInterfaceDetailW, SetupDiDestroyDeviceInfoList
 *      - HID.DLL:      HidD_GetHidGuid, HidD_GetAttributes, HidD_GetPreparsedData,
 *                      HidP_GetCaps, HidD_FreePreparsedData, HidD_SetNumInputBuffers,
 *                      HidD_GetSerialNumberString, HidD_GetFeature
 *      - KERNEL32.dll: CreateFileW, ReadFile, WriteFile, GetOverlappedResult,
 *                      CancelIoEx, CloseHandle
 *   2. Passes 100% of real HID devices and handles through untouched.
 *   3. When Local\LegacyPSMoveState->active == 1 (DualShock 4 mode active), appends
 *      a single virtual PS Move ZCM2 HID device to SetupAPI HID enumeration.
 *      When active == 0 (Camera mode or disconnected), remains completely invisible.
 *   4. Delivers 49-byte ZCM2 Input Reports (Report ID 0x01) over native overlapped
 *      ReadFile at ~100 Hz (4400 counts/G, 1015 counts/(rad/s)), and writes incoming
 *      sphere RGB + rumble output reports (0x06 / 0x02) back to shared memory for
 *      DualShock 4 Light Bar and rumble synchronization.
 *
 * Build (zero external runtime DLLs):
 *   x86: python -m ziglang c++ -target i686-windows-gnu -shared -O2 -fno-exceptions -fno-rtti \
 *            legacymove.cpp -o ../LegacyMove.dll -lwinmm
 *   x64: python -m ziglang c++ -target x86_64-windows-gnu -shared -O2 -fno-exceptions -fno-rtti \
 *            legacymove.cpp -o ../LegacyMove_x64.dll -lwinmm
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>

// ============================================================================
// Shared Memory Contract — Local\LegacyPSMoveState (128 bytes fixed)
// ============================================================================

static constexpr const wchar_t* kSharedMemName = L"Local\\LegacyPSMoveState";
static constexpr uint32_t kSharedMagic         = 0x314D5350u; // 'PSM1'
static constexpr uint32_t kSharedVersion       = 1u;

#pragma pack(push, 1)
struct PSMoveSharedState {
    // --- Sensor -> Game (64 bytes, seqlock guarded by `seq`) ---
    uint32_t magic;            // 0x314D5350 ('PSM1')
    uint32_t version;          // 1
    uint32_t seq;              // Seqlock: odd during write, even when consistent
    uint32_t active;           // 1 = virtual PS Move present & streaming, 0 = hidden
    uint64_t timestamp_ms;     // Monotonic / wall timestamp in ms
    uint32_t buttons_mask;     // Packed bytes[1..4] button flags (little-endian)
    uint8_t  trigger_analog;   // 0..255 analog trigger
    uint8_t  battery_code;     // 0..5 bars, 0xEE charging, 0xEF full
    uint16_t reserved0;
    int16_t  accel_x;          // ZCM2 raw counts (4400 = 1.0 G)
    int16_t  accel_y;
    int16_t  accel_z;
    int16_t  gyro_x;           // ZCM2 raw counts (1015 = 1.0 rad/s)
    int16_t  gyro_y;
    int16_t  gyro_z;
    uint8_t  reserved1[20];    // Pad Sensor->Game section to 64 bytes

    // --- Game -> Sensor Feedback (64 bytes, written exclusively by LegacyMove) ---
    uint32_t fb_seq;           // Incremented on output report / connect / disconnect
    uint32_t game_connected;   // 1 = game has open streaming handle, 0 = closed
    uint8_t  led_r;            // Sphere R (0..255)
    uint8_t  led_g;            // Sphere G (0..255)
    uint8_t  led_b;            // Sphere B (0..255)
    uint8_t  rumble;           // Rumble intensity (0..255)
    uint32_t game_pid;         // GetCurrentProcessId()
    uint32_t input_reports;    // Total 0x01 input reports delivered
    uint32_t output_reports;   // Total 0x06/0x02 output reports received
    uint8_t  reserved2[40];    // Pad total struct to 128 bytes
};
#pragma pack(pop)

static_assert(sizeof(PSMoveSharedState) == 128, "PSMoveSharedState must be exactly 128 bytes");
static_assert(offsetof(PSMoveSharedState, fb_seq) == 64, "Feedback block must start at offset 64");

// ============================================================================
// Win32 SetupAPI & HID ABI Definitions (exact x86 & x64 parity)
// ============================================================================

#ifndef DIGCF_DEVICEINTERFACE
#define DIGCF_DEVICEINTERFACE 0x00000010u
#endif

#ifndef SPINT_ACTIVE
#define SPINT_ACTIVE 0x00000001u
#endif

#ifndef ERROR_NO_MORE_ITEMS
#define ERROR_NO_MORE_ITEMS 259L
#endif

#ifndef ERROR_INSUFFICIENT_BUFFER
#define ERROR_INSUFFICIENT_BUFFER 122L
#endif

#ifndef ERROR_IO_PENDING
#define ERROR_IO_PENDING 997L
#endif

#ifndef ERROR_IO_INCOMPLETE
#define ERROR_IO_INCOMPLETE 996L
#endif

#ifndef ERROR_OPERATION_ABORTED
#define ERROR_OPERATION_ABORTED 995L
#endif

#ifndef ERROR_DEVICE_NOT_CONNECTED
#define ERROR_DEVICE_NOT_CONNECTED 1167L
#endif

#ifndef STATUS_PENDING
#define STATUS_PENDING ((ULONG_PTR)0x00000103u)
#endif

static constexpr LONG kHidpStatusSuccess = 0x00110000L;

static const GUID kHidClassGuid = {
    0x4D1E55B2u, 0xF16Fu, 0x11CFu,
    { 0x88u, 0xCBu, 0x00u, 0x11u, 0x11u, 0x00u, 0x00u, 0x30u }
};

#if defined(_WIN64)
#pragma pack(push, 8)
#else
#pragma pack(push, 1)
#endif
struct LM_SP_DEVINFO_DATA {
    DWORD     cbSize;
    GUID      ClassGuid;
    DWORD     DevInst;
    ULONG_PTR Reserved;
};

struct LM_SP_DEVICE_INTERFACE_DATA {
    DWORD     cbSize;
    GUID      InterfaceClassGuid;
    DWORD     Flags;
    ULONG_PTR Reserved;
};

struct LM_SP_DEVICE_INTERFACE_DETAIL_DATA_W {
    DWORD cbSize;
    WCHAR DevicePath[1];
};
#pragma pack(pop)

struct LM_HIDD_ATTRIBUTES {
    ULONG  Size;
    USHORT VendorID;
    USHORT ProductID;
    USHORT VersionNumber;
};

struct LM_HIDP_CAPS {
    USHORT Usage;
    USHORT UsagePage;
    USHORT InputReportByteLength;
    USHORT OutputReportByteLength;
    USHORT FeatureReportByteLength;
    USHORT Reserved[17];
    USHORT NumberLinkCollectionNodes;
    USHORT NumberInputButtonCaps;
    USHORT NumberInputValueCaps;
    USHORT NumberInputDataIndices;
    USHORT NumberOutputButtonCaps;
    USHORT NumberOutputValueCaps;
    USHORT NumberOutputDataIndices;
    USHORT NumberFeatureButtonCaps;
    USHORT NumberFeatureValueCaps;
    USHORT NumberFeatureDataIndices;
};

// Virtual PS Move identity constants (matches Sony PS Move ZCM2 PS4 Bluetooth)
static constexpr USHORT kSonyVid   = 0x054Cu;
static constexpr USHORT kMoveZcm2  = 0x0C5Eu;
static constexpr USHORT kMoveVer   = 0x0100u;
static constexpr USHORT kReportLen = 49u;

static constexpr const wchar_t* kVirtDevicePath =
    L"\\\\?\\hid#vid_054c&pid_0c5e&col01#legacypscam_vpmove_0#{4d1e55b2-f16f-11cf-88cb-001111000030}";
static constexpr const wchar_t* kVirtSerial = L"LEGACYDS4P1";

static constexpr ULONG_PTR kVirtualInterfaceTag = (ULONG_PTR)0x4C4D5630u; // 'LMV0'
static constexpr ULONG_PTR kVirtualPreparsedTag = (ULONG_PTR)0x4C4D5050u; // 'LMPP'

// ============================================================================
// Original Win32 Function Pointer Types
// ============================================================================

using Fn_SetupDiGetClassDevsW = HANDLE(WINAPI*)(const GUID*, PCWSTR, HWND, DWORD);
using Fn_SetupDiEnumDeviceInterfaces = BOOL(WINAPI*)(HANDLE, LM_SP_DEVINFO_DATA*, const GUID*, DWORD, LM_SP_DEVICE_INTERFACE_DATA*);
using Fn_SetupDiGetDeviceInterfaceDetailW = BOOL(WINAPI*)(HANDLE, LM_SP_DEVICE_INTERFACE_DATA*, LM_SP_DEVICE_INTERFACE_DETAIL_DATA_W*, DWORD, DWORD*, LM_SP_DEVINFO_DATA*);
using Fn_SetupDiDestroyDeviceInfoList = BOOL(WINAPI*)(HANDLE);

using Fn_HidD_GetHidGuid = void(WINAPI*)(GUID*);
using Fn_HidD_GetAttributes = BOOLEAN(WINAPI*)(HANDLE, LM_HIDD_ATTRIBUTES*);
using Fn_HidD_GetPreparsedData = BOOLEAN(WINAPI*)(HANDLE, void**);
using Fn_HidP_GetCaps = LONG(WINAPI*)(void*, LM_HIDP_CAPS*);
using Fn_HidD_FreePreparsedData = BOOLEAN(WINAPI*)(void*);
using Fn_HidD_SetNumInputBuffers = BOOLEAN(WINAPI*)(HANDLE, ULONG);
using Fn_HidD_GetSerialNumberString = BOOLEAN(WINAPI*)(HANDLE, void*, ULONG);
using Fn_HidD_GetFeature = BOOLEAN(WINAPI*)(HANDLE, void*, ULONG);

using Fn_CreateFileW = HANDLE(WINAPI*)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
using Fn_ReadFile = BOOL(WINAPI*)(HANDLE, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);
using Fn_WriteFile = BOOL(WINAPI*)(HANDLE, LPCVOID, DWORD, LPDWORD, LPOVERLAPPED);
using Fn_GetOverlappedResult = BOOL(WINAPI*)(HANDLE, LPOVERLAPPED, LPDWORD, BOOL);
using Fn_CancelIoEx = BOOL(WINAPI*)(HANDLE, LPOVERLAPPED);
using Fn_CloseHandle = BOOL(WINAPI*)(HANDLE);

static Fn_SetupDiGetClassDevsW             g_origSetupDiGetClassDevsW = nullptr;
static Fn_SetupDiEnumDeviceInterfaces      g_origSetupDiEnumDeviceInterfaces = nullptr;
static Fn_SetupDiGetDeviceInterfaceDetailW g_origSetupDiGetDeviceInterfaceDetailW = nullptr;
static Fn_SetupDiDestroyDeviceInfoList     g_origSetupDiDestroyDeviceInfoList = nullptr;

static Fn_HidD_GetHidGuid                  g_origHidD_GetHidGuid = nullptr;
static Fn_HidD_GetAttributes               g_origHidD_GetAttributes = nullptr;
static Fn_HidD_GetPreparsedData            g_origHidD_GetPreparsedData = nullptr;
static Fn_HidP_GetCaps                     g_origHidP_GetCaps = nullptr;
static Fn_HidD_FreePreparsedData           g_origHidD_FreePreparsedData = nullptr;
static Fn_HidD_SetNumInputBuffers          g_origHidD_SetNumInputBuffers = nullptr;
static Fn_HidD_GetSerialNumberString       g_origHidD_GetSerialNumberString = nullptr;
static Fn_HidD_GetFeature                  g_origHidD_GetFeature = nullptr;

static Fn_CreateFileW                      g_origCreateFileW = nullptr;
static Fn_ReadFile                         g_origReadFile = nullptr;
static Fn_WriteFile                        g_origWriteFile = nullptr;
static Fn_GetOverlappedResult              g_origGetOverlappedResult = nullptr;
static Fn_CancelIoEx                       g_origCancelIoEx = nullptr;
static Fn_CloseHandle                      g_origCloseHandle = nullptr;

// ============================================================================
// Global State & Shared Memory Access
// ============================================================================

static CRITICAL_SECTION g_lock;
static bool             g_lockReady = false;
static LONG             g_hookedCount = 0;

static HANDLE             g_shmHandle = nullptr;
static PSMoveSharedState* g_shmView = nullptr;
static DWORD              g_lastShmProbeTick = 0;

struct TrackedDevInfo {
    HANDLE hDevInfo;
    DWORD  realCount;
    bool   inUse;
};

static constexpr int kMaxDevInfo = 32;
static TrackedDevInfo g_devInfos[kMaxDevInfo] = {};

struct VirtualHandleSlot {
    bool         inUse;
    HANDLE       hToken;        // Real OS event handle used as collision-free token
    bool         isStreaming;   // Opened with GENERIC_READ
    bool         isOverlapped;

    // Pending overlapped read state (protected by g_lock)
    bool         readPending;
    uint8_t*     readBuf;
    DWORD        readBufLen;
    LPOVERLAPPED readOv;
    DWORD        lastCompletedBytes;
    DWORD        lastError;

    // Report sequencing
    uint8_t      seq4;
    uint16_t     ts16;
    DWORD        lastReportTickMs;

    // 100 Hz pacer thread (active only while streaming handle is open)
    HANDLE       hStopEvent;
    HANDLE       hPacerThread;
};

static constexpr int kMaxVirtHandles = 8;
static VirtualHandleSlot g_virtHandles[kMaxVirtHandles] = {};

static bool IsSameWStrIgnoreCase(const wchar_t* a, const wchar_t* b) {
    if (!a || !b) return false;
    while (*a && *b) {
        wchar_t ca = (*a >= L'A' && *a <= L'Z') ? (wchar_t)(*a + 32) : *a;
        wchar_t cb = (*b >= L'A' && *b <= L'Z') ? (wchar_t)(*b + 32) : *b;
        if (ca != cb) return false;
        ++a;
        ++b;
    }
    return *a == 0 && *b == 0;
}

static bool IsSameAsciiIgnoreCase(const char* a, const char* b) {
    if (!a || !b) return false;
    while (*a && *b) {
        char ca = (*a >= 'A' && *a <= 'Z') ? (char)(*a + 32) : *a;
        char cb = (*b >= 'A' && *b <= 'Z') ? (char)(*b + 32) : *b;
        if (ca != cb) return false;
        ++a;
        ++b;
    }
    return *a == 0 && *b == 0;
}

static PSMoveSharedState* EnsureSharedMemoryLocked() {
    if (g_shmView != nullptr) {
        return g_shmView;
    }
    DWORD now = GetTickCount();
    if (g_lastShmProbeTick != 0 && (now - g_lastShmProbeTick) < 200u) {
        return nullptr;
    }
    g_lastShmProbeTick = now;

    HANDLE hMap = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, kSharedMemName);
    if (!hMap) {
        return nullptr;
    }
    void* view = MapViewOfFile(hMap, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, sizeof(PSMoveSharedState));
    if (!view) {
        if (g_origCloseHandle) g_origCloseHandle(hMap);
        else CloseHandle(hMap);
        return nullptr;
    }
    g_shmHandle = hMap;
    g_shmView = reinterpret_cast<PSMoveSharedState*>(view);
    return g_shmView;
}

static bool ReadSharedSnapshot(PSMoveSharedState* outSnap) {
    if (!outSnap) return false;
    EnterCriticalSection(&g_lock);
    PSMoveSharedState* shm = EnsureSharedMemoryLocked();
    if (!shm) {
        LeaveCriticalSection(&g_lock);
        return false;
    }
    for (int attempt = 0; attempt < 8; ++attempt) {
        uint32_t s1 = *(volatile uint32_t*)&shm->seq;
        MemoryBarrier();
        if (s1 & 1u) continue;
        memcpy(outSnap, shm, 64);
        MemoryBarrier();
        uint32_t s2 = *(volatile uint32_t*)&shm->seq;
        if (s1 == s2) {
            LeaveCriticalSection(&g_lock);
            return (outSnap->magic == kSharedMagic && outSnap->version == kSharedVersion);
        }
    }
    LeaveCriticalSection(&g_lock);
    return false;
}

static bool IsVirtualMoveActive() {
    PSMoveSharedState snap = {};
    if (!ReadSharedSnapshot(&snap)) return false;
    return snap.active != 0u;
}

static void WriteFeedbackConnected(bool connected) {
    EnterCriticalSection(&g_lock);
    PSMoveSharedState* shm = EnsureSharedMemoryLocked();
    if (shm && shm->magic == kSharedMagic) {
        shm->game_connected = connected ? 1u : 0u;
        shm->game_pid = GetCurrentProcessId();
        if (!connected) {
            shm->rumble = 0;
        }
        MemoryBarrier();
        shm->fb_seq = shm->fb_seq + 1u;
    }
    LeaveCriticalSection(&g_lock);
}

static void WriteFeedbackOutputReport(uint8_t r, uint8_t g, uint8_t b, uint8_t rumble) {
    EnterCriticalSection(&g_lock);
    PSMoveSharedState* shm = EnsureSharedMemoryLocked();
    if (shm && shm->magic == kSharedMagic) {
        shm->game_connected = 1u;
        shm->game_pid = GetCurrentProcessId();
        shm->led_r = r;
        shm->led_g = g;
        shm->led_b = b;
        shm->rumble = rumble;
        shm->output_reports = shm->output_reports + 1u;
        MemoryBarrier();
        shm->fb_seq = shm->fb_seq + 1u;
    }
    LeaveCriticalSection(&g_lock);
}

static void BumpInputReportCounter() {
    EnterCriticalSection(&g_lock);
    PSMoveSharedState* shm = EnsureSharedMemoryLocked();
    if (shm && shm->magic == kSharedMagic) {
        shm->input_reports = shm->input_reports + 1u;
    }
    LeaveCriticalSection(&g_lock);
}

// ============================================================================
// ZCM2 49-Byte Input Report Builder (Report ID 0x01)
// ============================================================================

static void PackZcm2InputReport(uint8_t* dst, DWORD dstLen, const PSMoveSharedState& snap, uint8_t seq4, uint16_t ts16) {
    if (!dst || dstLen < kReportLen) return;
    memset(dst, 0, dstLen);

    dst[0] = 0x01u; // Report ID

    // Buttons bytes 1..4 (LE mask from Python) + 4-bit rolling sequence in low nibble of byte 4
    uint32_t btns = snap.buttons_mask;
    dst[1] = (uint8_t)(btns & 0xFFu);
    dst[2] = (uint8_t)((btns >> 8) & 0xFFu);
    dst[3] = (uint8_t)((btns >> 16) & 0xFFu);
    dst[4] = (uint8_t)(((btns >> 24) & 0xF0u) | (seq4 & 0x0Fu));

    // Analog trigger (ZCM2 reads byte 5)
    dst[5] = snap.trigger_analog;

    // 16-bit timestamp (high at byte 11, low at byte 43)
    dst[11] = (uint8_t)((ts16 >> 8) & 0xFFu);
    dst[43] = (uint8_t)(ts16 & 0xFFu);

    // Battery code (0..5, 0xEE charging, 0xEF full)
    dst[12] = snap.battery_code;

    // Signed 16-bit LE accelerometer (4400 counts/G)
    int16_t ax = snap.accel_x;
    int16_t ay = snap.accel_y;
    int16_t az = snap.accel_z;
    dst[13] = (uint8_t)((uint16_t)ax & 0xFFu);
    dst[14] = (uint8_t)(((uint16_t)ax >> 8) & 0xFFu);
    dst[15] = (uint8_t)((uint16_t)ay & 0xFFu);
    dst[16] = (uint8_t)(((uint16_t)ay >> 8) & 0xFFu);
    dst[17] = (uint8_t)((uint16_t)az & 0xFFu);
    dst[18] = (uint8_t)(((uint16_t)az >> 8) & 0xFFu);

    // Signed 16-bit LE gyroscope (1015 counts/(rad/s))
    int16_t gx = snap.gyro_x;
    int16_t gy = snap.gyro_y;
    int16_t gz = snap.gyro_z;
    dst[25] = (uint8_t)((uint16_t)gx & 0xFFu);
    dst[26] = (uint8_t)(((uint16_t)gx >> 8) & 0xFFu);
    dst[27] = (uint8_t)((uint16_t)gy & 0xFFu);
    dst[28] = (uint8_t)(((uint16_t)gy >> 8) & 0xFFu);
    dst[29] = (uint8_t)((uint16_t)gz & 0xFFu);
    dst[30] = (uint8_t)(((uint16_t)gz >> 8) & 0xFFu);
}

// ============================================================================
// Virtual Handle Helpers & 100 Hz Overlapped Pacer Thread
// ============================================================================

static VirtualHandleSlot* FindVirtHandleLocked(HANDLE h) {
    if (!h || h == INVALID_HANDLE_VALUE) return nullptr;
    for (int i = 0; i < kMaxVirtHandles; ++i) {
        if (g_virtHandles[i].inUse && g_virtHandles[i].hToken == h) {
            return &g_virtHandles[i];
        }
    }
    return nullptr;
}

static DWORD WINAPI PacerThreadProc(LPVOID param) {
    int slotIdx = (int)(intptr_t)param;
    timeBeginPeriod(1);

    for (;;) {
        HANDLE hStop = nullptr;
        EnterCriticalSection(&g_lock);
        if (slotIdx < 0 || slotIdx >= kMaxVirtHandles || !g_virtHandles[slotIdx].inUse) {
            LeaveCriticalSection(&g_lock);
            break;
        }
        hStop = g_virtHandles[slotIdx].hStopEvent;
        LeaveCriticalSection(&g_lock);

        if (!hStop || WaitForSingleObject(hStop, 2) == WAIT_OBJECT_0) {
            break;
        }

        PSMoveSharedState snap = {};
        bool okSnap = ReadSharedSnapshot(&snap);
        bool active = okSnap && (snap.active != 0u);

        DWORD nowMs = GetTickCount();
        HANDLE eventToSignal = nullptr;
        bool delivered = false;

        EnterCriticalSection(&g_lock);
        VirtualHandleSlot& slot = g_virtHandles[slotIdx];
        if (!slot.inUse) {
            LeaveCriticalSection(&g_lock);
            break;
        }
        if (slot.readPending && slot.readOv != nullptr) {
            if (!active) {
                slot.readPending = false;
                slot.lastCompletedBytes = 0;
                slot.lastError = ERROR_DEVICE_NOT_CONNECTED;
                slot.readOv->Internal = 0;
                slot.readOv->InternalHigh = 0;
                eventToSignal = slot.readOv->hEvent;
            } else if ((nowMs - slot.lastReportTickMs) >= 10u) {
                slot.lastReportTickMs = nowMs;
                slot.seq4 = (uint8_t)((slot.seq4 + 1u) & 0x0Fu);
                slot.ts16 = (uint16_t)(slot.ts16 + 10u);
                PackZcm2InputReport(slot.readBuf, slot.readBufLen, snap, slot.seq4, slot.ts16);
                slot.readPending = false;
                slot.lastCompletedBytes = (slot.readBufLen >= kReportLen) ? kReportLen : slot.readBufLen;
                slot.lastError = 0;
                slot.readOv->Internal = 0;
                slot.readOv->InternalHigh = slot.lastCompletedBytes;
                eventToSignal = slot.readOv->hEvent;
                delivered = true;
            }
        }
        LeaveCriticalSection(&g_lock);

        if (delivered) {
            BumpInputReportCounter();
        }
        if (eventToSignal != nullptr) {
            SetEvent(eventToSignal);
        }
    }

    timeEndPeriod(1);
    return 0;
}

// ============================================================================
// SetupAPI Hooks
// ============================================================================

static HANDLE WINAPI Hook_SetupDiGetClassDevsW(const GUID* ClassGuid, PCWSTR Enumerator, HWND hwndParent, DWORD Flags) {
    HANDLE h = g_origSetupDiGetClassDevsW(ClassGuid, Enumerator, hwndParent, Flags);
    if (h && h != INVALID_HANDLE_VALUE && ClassGuid != nullptr && (Flags & DIGCF_DEVICEINTERFACE)) {
        if (memcmp(ClassGuid, &kHidClassGuid, sizeof(GUID)) == 0) {
            EnterCriticalSection(&g_lock);
            for (int i = 0; i < kMaxDevInfo; ++i) {
                if (!g_devInfos[i].inUse) {
                    g_devInfos[i].inUse = true;
                    g_devInfos[i].hDevInfo = h;
                    g_devInfos[i].realCount = 0;
                    break;
                }
            }
            LeaveCriticalSection(&g_lock);
        }
    }
    return h;
}

static BOOL WINAPI Hook_SetupDiEnumDeviceInterfaces(
    HANDLE DeviceInfoSet,
    LM_SP_DEVINFO_DATA* DeviceInfoData,
    const GUID* InterfaceClassGuid,
    DWORD MemberIndex,
    LM_SP_DEVICE_INTERFACE_DATA* DeviceInterfaceData
) {
    BOOL res = g_origSetupDiEnumDeviceInterfaces(
        DeviceInfoSet, DeviceInfoData, InterfaceClassGuid, MemberIndex, DeviceInterfaceData
    );

    if (res) {
        EnterCriticalSection(&g_lock);
        for (int i = 0; i < kMaxDevInfo; ++i) {
            if (g_devInfos[i].inUse && g_devInfos[i].hDevInfo == DeviceInfoSet) {
                if (MemberIndex + 1u > g_devInfos[i].realCount) {
                    g_devInfos[i].realCount = MemberIndex + 1u;
                }
                break;
            }
        }
        LeaveCriticalSection(&g_lock);
        return TRUE;
    }

    DWORD err = GetLastError();
    if (err == ERROR_NO_MORE_ITEMS && DeviceInterfaceData != nullptr && InterfaceClassGuid != nullptr &&
        memcmp(InterfaceClassGuid, &kHidClassGuid, sizeof(GUID)) == 0) {
        bool shouldEmitVirtual = false;
        EnterCriticalSection(&g_lock);
        for (int i = 0; i < kMaxDevInfo; ++i) {
            if (g_devInfos[i].inUse && g_devInfos[i].hDevInfo == DeviceInfoSet) {
                if (MemberIndex == g_devInfos[i].realCount) {
                    shouldEmitVirtual = true;
                }
                break;
            }
        }
        LeaveCriticalSection(&g_lock);

        if (shouldEmitVirtual && IsVirtualMoveActive()) {
            DeviceInterfaceData->InterfaceClassGuid = kHidClassGuid;
            DeviceInterfaceData->Flags = SPINT_ACTIVE;
            DeviceInterfaceData->Reserved = kVirtualInterfaceTag;
            SetLastError(ERROR_SUCCESS);
            return TRUE;
        }
    }

    SetLastError(err);
    return FALSE;
}

static BOOL WINAPI Hook_SetupDiGetDeviceInterfaceDetailW(
    HANDLE DeviceInfoSet,
    LM_SP_DEVICE_INTERFACE_DATA* DeviceInterfaceData,
    LM_SP_DEVICE_INTERFACE_DETAIL_DATA_W* DeviceInterfaceDetailData,
    DWORD DeviceInterfaceDetailDataSize,
    DWORD* RequiredSize,
    LM_SP_DEVINFO_DATA* DeviceInfoData
) {
    if (DeviceInterfaceData != nullptr && DeviceInterfaceData->Reserved == kVirtualInterfaceTag) {
        const size_t pathChars = wcslen(kVirtDevicePath) + 1u;
        const DWORD reqBytes = (DWORD)(4u + pathChars * sizeof(WCHAR));
        if (RequiredSize != nullptr) {
            *RequiredSize = reqBytes;
        }
        if (DeviceInterfaceDetailData == nullptr || DeviceInterfaceDetailDataSize < reqBytes) {
            SetLastError(ERROR_INSUFFICIENT_BUFFER);
            return FALSE;
        }
        // DevicePath always begins at byte offset +4 in both x86 and x64
        memcpy(reinterpret_cast<uint8_t*>(DeviceInterfaceDetailData) + 4, kVirtDevicePath, pathChars * sizeof(WCHAR));
        if (DeviceInfoData != nullptr) {
            memset(&DeviceInfoData->ClassGuid, 0, sizeof(GUID));
            DeviceInfoData->DevInst = 0;
            DeviceInfoData->Reserved = 0;
        }
        SetLastError(ERROR_SUCCESS);
        return TRUE;
    }

    return g_origSetupDiGetDeviceInterfaceDetailW(
        DeviceInfoSet, DeviceInterfaceData, DeviceInterfaceDetailData,
        DeviceInterfaceDetailDataSize, RequiredSize, DeviceInfoData
    );
}

static BOOL WINAPI Hook_SetupDiDestroyDeviceInfoList(HANDLE DeviceInfoSet) {
    EnterCriticalSection(&g_lock);
    for (int i = 0; i < kMaxDevInfo; ++i) {
        if (g_devInfos[i].inUse && g_devInfos[i].hDevInfo == DeviceInfoSet) {
            g_devInfos[i].inUse = false;
            g_devInfos[i].hDevInfo = nullptr;
            g_devInfos[i].realCount = 0;
            break;
        }
    }
    LeaveCriticalSection(&g_lock);
    return g_origSetupDiDestroyDeviceInfoList(DeviceInfoSet);
}

// ============================================================================
// HID.DLL Hooks
// ============================================================================

static void WINAPI Hook_HidD_GetHidGuid(GUID* HidGuid) {
    if (g_origHidD_GetHidGuid) {
        g_origHidD_GetHidGuid(HidGuid);
    } else if (HidGuid) {
        *HidGuid = kHidClassGuid;
    }
}

static BOOLEAN WINAPI Hook_HidD_GetAttributes(HANDLE HidDeviceObject, LM_HIDD_ATTRIBUTES* Attributes) {
    EnterCriticalSection(&g_lock);
    bool isVirt = (FindVirtHandleLocked(HidDeviceObject) != nullptr);
    LeaveCriticalSection(&g_lock);

    if (isVirt) {
        if (!Attributes) return 0;
        Attributes->Size = sizeof(LM_HIDD_ATTRIBUTES);
        Attributes->VendorID = kSonyVid;
        Attributes->ProductID = kMoveZcm2;
        Attributes->VersionNumber = kMoveVer;
        return 1;
    }
    return g_origHidD_GetAttributes(HidDeviceObject, Attributes);
}

static BOOLEAN WINAPI Hook_HidD_GetPreparsedData(HANDLE HidDeviceObject, void** PreparsedData) {
    EnterCriticalSection(&g_lock);
    bool isVirt = (FindVirtHandleLocked(HidDeviceObject) != nullptr);
    LeaveCriticalSection(&g_lock);

    if (isVirt) {
        if (!PreparsedData) return 0;
        *PreparsedData = reinterpret_cast<void*>(kVirtualPreparsedTag);
        return 1;
    }
    return g_origHidD_GetPreparsedData(HidDeviceObject, PreparsedData);
}

static LONG WINAPI Hook_HidP_GetCaps(void* PreparsedData, LM_HIDP_CAPS* Capabilities) {
    if (PreparsedData == reinterpret_cast<void*>(kVirtualPreparsedTag)) {
        if (!Capabilities) return 0;
        memset(Capabilities, 0, sizeof(LM_HIDP_CAPS));
        Capabilities->Usage = 0x04u;                   // Joystick
        Capabilities->UsagePage = 0x01u;               // Generic Desktop
        Capabilities->InputReportByteLength = kReportLen;  // 49 bytes (>= 0x25)
        Capabilities->OutputReportByteLength = kReportLen; // 49 bytes (>= 9)
        Capabilities->FeatureReportByteLength = 0u;    // Skip feature 0x10 -> exact 4400/G & 1015/(rad/s)
        return kHidpStatusSuccess;
    }
    return g_origHidP_GetCaps(PreparsedData, Capabilities);
}

static BOOLEAN WINAPI Hook_HidD_FreePreparsedData(void* PreparsedData) {
    if (PreparsedData == reinterpret_cast<void*>(kVirtualPreparsedTag)) {
        return 1;
    }
    return g_origHidD_FreePreparsedData(PreparsedData);
}

static BOOLEAN WINAPI Hook_HidD_SetNumInputBuffers(HANDLE HidDeviceObject, ULONG NumberBuffers) {
    EnterCriticalSection(&g_lock);
    bool isVirt = (FindVirtHandleLocked(HidDeviceObject) != nullptr);
    LeaveCriticalSection(&g_lock);

    if (isVirt) {
        return 1;
    }
    return g_origHidD_SetNumInputBuffers(HidDeviceObject, NumberBuffers);
}

static BOOLEAN WINAPI Hook_HidD_GetSerialNumberString(HANDLE HidDeviceObject, void* Buffer, ULONG BufferLength) {
    EnterCriticalSection(&g_lock);
    bool isVirt = (FindVirtHandleLocked(HidDeviceObject) != nullptr);
    LeaveCriticalSection(&g_lock);

    if (isVirt) {
        if (!Buffer || BufferLength < 4u) return 0;
        const size_t chars = wcslen(kVirtSerial) + 1u;
        const size_t bytesNeeded = chars * sizeof(WCHAR);
        if (bytesNeeded > BufferLength) {
            size_t maxChars = (BufferLength / sizeof(WCHAR)) - 1u;
            memcpy(Buffer, kVirtSerial, maxChars * sizeof(WCHAR));
            reinterpret_cast<WCHAR*>(Buffer)[maxChars] = 0;
        } else {
            memcpy(Buffer, kVirtSerial, bytesNeeded);
        }
        return 1;
    }
    return g_origHidD_GetSerialNumberString(HidDeviceObject, Buffer, BufferLength);
}

static BOOLEAN WINAPI Hook_HidD_GetFeature(HANDLE HidDeviceObject, void* ReportBuffer, ULONG ReportBufferLength) {
    EnterCriticalSection(&g_lock);
    bool isVirt = (FindVirtHandleLocked(HidDeviceObject) != nullptr);
    LeaveCriticalSection(&g_lock);

    if (isVirt) {
        SetLastError(ERROR_NOT_SUPPORTED);
        return 0;
    }
    return g_origHidD_GetFeature ? g_origHidD_GetFeature(HidDeviceObject, ReportBuffer, ReportBufferLength) : 0;
}

// ============================================================================
// KERNEL32.dll File I/O Hooks (Virtual Handle Interception)
// ============================================================================

static HANDLE WINAPI Hook_CreateFileW(
    LPCWSTR lpFileName,
    DWORD dwDesiredAccess,
    DWORD dwShareMode,
    LPSECURITY_ATTRIBUTES lpSecurityAttributes,
    DWORD dwCreationDisposition,
    DWORD dwFlagsAndAttributes,
    HANDLE hTemplateFile
) {
    if (lpFileName != nullptr && IsSameWStrIgnoreCase(lpFileName, kVirtDevicePath)) {
        if (!IsVirtualMoveActive()) {
            SetLastError(ERROR_FILE_NOT_FOUND);
            return INVALID_HANDLE_VALUE;
        }

        HANDLE hToken = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!hToken) {
            return INVALID_HANDLE_VALUE;
        }

        const bool isStreaming = (dwDesiredAccess & GENERIC_READ) != 0u;
        const bool isOverlapped = (dwFlagsAndAttributes & FILE_FLAG_OVERLAPPED) != 0u;
        HANDLE hStop = isStreaming ? CreateEventW(nullptr, TRUE, FALSE, nullptr) : nullptr;

        int chosenIdx = -1;
        EnterCriticalSection(&g_lock);
        for (int i = 0; i < kMaxVirtHandles; ++i) {
            if (!g_virtHandles[i].inUse) {
                chosenIdx = i;
                VirtualHandleSlot& slot = g_virtHandles[i];
                memset(&slot, 0, sizeof(slot));
                slot.inUse = true;
                slot.hToken = hToken;
                slot.isStreaming = isStreaming;
                slot.isOverlapped = isOverlapped;
                slot.lastReportTickMs = GetTickCount() - 20u; // First report ready immediately
                slot.hStopEvent = hStop;
                break;
            }
        }
        LeaveCriticalSection(&g_lock);

        if (chosenIdx < 0) {
            if (hStop) g_origCloseHandle(hStop);
            g_origCloseHandle(hToken);
            SetLastError(ERROR_TOO_MANY_OPEN_FILES);
            return INVALID_HANDLE_VALUE;
        }

        if (isStreaming) {
            HANDLE hThread = CreateThread(nullptr, 0, PacerThreadProc, (LPVOID)(intptr_t)chosenIdx, 0, nullptr);
            EnterCriticalSection(&g_lock);
            g_virtHandles[chosenIdx].hPacerThread = hThread;
            LeaveCriticalSection(&g_lock);
            WriteFeedbackConnected(true);
        }

        SetLastError(ERROR_SUCCESS);
        return hToken;
    }

    return g_origCreateFileW(
        lpFileName, dwDesiredAccess, dwShareMode, lpSecurityAttributes,
        dwCreationDisposition, dwFlagsAndAttributes, hTemplateFile
    );
}

static BOOL WINAPI Hook_ReadFile(
    HANDLE hFile,
    LPVOID lpBuffer,
    DWORD nNumberOfBytesToRead,
    LPDWORD lpNumberOfBytesRead,
    LPOVERLAPPED lpOverlapped
) {
    EnterCriticalSection(&g_lock);
    VirtualHandleSlot* slot = FindVirtHandleLocked(hFile);
    if (!slot) {
        LeaveCriticalSection(&g_lock);
        return g_origReadFile(hFile, lpBuffer, nNumberOfBytesToRead, lpNumberOfBytesRead, lpOverlapped);
    }

    if (lpOverlapped != nullptr && lpOverlapped->hEvent != nullptr) {
        ResetEvent(lpOverlapped->hEvent);
    }
    LeaveCriticalSection(&g_lock);

    PSMoveSharedState snap = {};
    if (!ReadSharedSnapshot(&snap) || snap.active == 0u) {
        SetLastError(ERROR_DEVICE_NOT_CONNECTED);
        return FALSE;
    }

    DWORD nowMs = GetTickCount();
    EnterCriticalSection(&g_lock);
    slot = FindVirtHandleLocked(hFile);
    if (!slot) {
        LeaveCriticalSection(&g_lock);
        SetLastError(ERROR_INVALID_HANDLE);
        return FALSE;
    }

    if (lpBuffer == nullptr || nNumberOfBytesToRead < kReportLen) {
        LeaveCriticalSection(&g_lock);
        SetLastError(ERROR_INSUFFICIENT_BUFFER);
        return FALSE;
    }

    // Immediate completion if >= 10 ms elapsed since previous report
    if ((nowMs - slot->lastReportTickMs) >= 10u || lpOverlapped == nullptr) {
        slot->lastReportTickMs = nowMs;
        slot->seq4 = (uint8_t)((slot->seq4 + 1u) & 0x0Fu);
        slot->ts16 = (uint16_t)(slot->ts16 + 10u);
        PackZcm2InputReport(reinterpret_cast<uint8_t*>(lpBuffer), nNumberOfBytesToRead, snap, slot->seq4, slot->ts16);
        slot->readPending = false;
        slot->lastCompletedBytes = kReportLen;
        slot->lastError = 0;
        if (lpNumberOfBytesRead != nullptr) {
            *lpNumberOfBytesRead = kReportLen;
        }
        HANDLE ev = nullptr;
        if (lpOverlapped != nullptr) {
            lpOverlapped->Internal = 0;
            lpOverlapped->InternalHigh = kReportLen;
            ev = lpOverlapped->hEvent;
        }
        LeaveCriticalSection(&g_lock);
        BumpInputReportCounter();
        if (ev != nullptr) SetEvent(ev);
        SetLastError(ERROR_SUCCESS);
        return TRUE;
    }

    // Otherwise pend asynchronously; the 100 Hz pacer thread completes & signals hEvent
    slot->readPending = true;
    slot->readBuf = reinterpret_cast<uint8_t*>(lpBuffer);
    slot->readBufLen = nNumberOfBytesToRead;
    slot->readOv = lpOverlapped;
    slot->lastCompletedBytes = 0;
    slot->lastError = 0;
    lpOverlapped->Internal = STATUS_PENDING;
    lpOverlapped->InternalHigh = 0;
    LeaveCriticalSection(&g_lock);

    SetLastError(ERROR_IO_PENDING);
    return FALSE;
}

static BOOL WINAPI Hook_WriteFile(
    HANDLE hFile,
    LPCVOID lpBuffer,
    DWORD nNumberOfBytesToWrite,
    LPDWORD lpNumberOfBytesWritten,
    LPOVERLAPPED lpOverlapped
) {
    EnterCriticalSection(&g_lock);
    bool isVirt = (FindVirtHandleLocked(hFile) != nullptr);
    LeaveCriticalSection(&g_lock);

    if (!isVirt) {
        return g_origWriteFile(hFile, lpBuffer, nNumberOfBytesToWrite, lpNumberOfBytesWritten, lpOverlapped);
    }

    if (lpBuffer != nullptr && nNumberOfBytesToWrite >= 7u) {
        const uint8_t* bytes = reinterpret_cast<const uint8_t*>(lpBuffer);
        uint8_t repId = bytes[0];
        if (repId == 0x06u || repId == 0x02u) {
            uint8_t r = bytes[2];
            uint8_t g = bytes[3];
            uint8_t b = bytes[4];
            uint8_t rumble = bytes[6];
            WriteFeedbackOutputReport(r, g, b, rumble);
        }
    }

    if (lpNumberOfBytesWritten != nullptr) {
        *lpNumberOfBytesWritten = nNumberOfBytesToWrite;
    }
    if (lpOverlapped != nullptr) {
        lpOverlapped->Internal = 0;
        lpOverlapped->InternalHigh = nNumberOfBytesToWrite;
        if (lpOverlapped->hEvent != nullptr) {
            SetEvent(lpOverlapped->hEvent);
        }
    }
    SetLastError(ERROR_SUCCESS);
    return TRUE;
}

static BOOL WINAPI Hook_GetOverlappedResult(
    HANDLE hFile,
    LPOVERLAPPED lpOverlapped,
    LPDWORD lpNumberOfBytesTransferred,
    BOOL bWait
) {
    EnterCriticalSection(&g_lock);
    VirtualHandleSlot* slot = FindVirtHandleLocked(hFile);
    if (!slot) {
        LeaveCriticalSection(&g_lock);
        return g_origGetOverlappedResult(hFile, lpOverlapped, lpNumberOfBytesTransferred, bWait);
    }

    // Write overlapped operations complete synchronously inside Hook_WriteFile
    if (lpOverlapped != nullptr && lpOverlapped != slot->readOv) {
        DWORD xfer = (DWORD)lpOverlapped->InternalHigh;
        LeaveCriticalSection(&g_lock);
        if (lpNumberOfBytesTransferred != nullptr) {
            *lpNumberOfBytesTransferred = xfer;
        }
        SetLastError(ERROR_SUCCESS);
        return TRUE;
    }

    if (slot->readPending) {
        if (!bWait) {
            LeaveCriticalSection(&g_lock);
            SetLastError(ERROR_IO_INCOMPLETE);
            return FALSE;
        }
        HANDLE ev = (lpOverlapped != nullptr) ? lpOverlapped->hEvent : nullptr;
        LeaveCriticalSection(&g_lock);
        if (ev != nullptr) {
            WaitForSingleObject(ev, 500);
        }
        EnterCriticalSection(&g_lock);
        slot = FindVirtHandleLocked(hFile);
        if (!slot) {
            LeaveCriticalSection(&g_lock);
            SetLastError(ERROR_INVALID_HANDLE);
            return FALSE;
        }
    }

    DWORD err = slot->lastError;
    DWORD bytes = slot->lastCompletedBytes;
    LeaveCriticalSection(&g_lock);

    if (err != 0) {
        if (lpNumberOfBytesTransferred != nullptr) *lpNumberOfBytesTransferred = 0;
        SetLastError(err);
        return FALSE;
    }
    if (lpNumberOfBytesTransferred != nullptr) {
        *lpNumberOfBytesTransferred = bytes;
    }
    SetLastError(ERROR_SUCCESS);
    return TRUE;
}

static BOOL WINAPI Hook_CancelIoEx(HANDLE hFile, LPOVERLAPPED lpOverlapped) {
    EnterCriticalSection(&g_lock);
    VirtualHandleSlot* slot = FindVirtHandleLocked(hFile);
    if (!slot) {
        LeaveCriticalSection(&g_lock);
        return g_origCancelIoEx ? g_origCancelIoEx(hFile, lpOverlapped) : FALSE;
    }

    HANDLE evToSignal = nullptr;
    if (slot->readPending && (lpOverlapped == nullptr || lpOverlapped == slot->readOv)) {
        slot->readPending = false;
        slot->lastCompletedBytes = 0;
        slot->lastError = ERROR_OPERATION_ABORTED;
        if (slot->readOv != nullptr) {
            slot->readOv->Internal = 0;
            slot->readOv->InternalHigh = 0;
            evToSignal = slot->readOv->hEvent;
        }
    }
    LeaveCriticalSection(&g_lock);

    if (evToSignal != nullptr) {
        SetEvent(evToSignal);
    }
    SetLastError(ERROR_SUCCESS);
    return TRUE;
}

static BOOL WINAPI Hook_CloseHandle(HANDLE hObject) {
    HANDLE hStop = nullptr;
    HANDLE hThread = nullptr;
    bool wasStreaming = false;
    bool isVirt = false;

    EnterCriticalSection(&g_lock);
    VirtualHandleSlot* slot = FindVirtHandleLocked(hObject);
    if (slot) {
        isVirt = true;
        wasStreaming = slot->isStreaming;
        hStop = slot->hStopEvent;
        hThread = slot->hPacerThread;
        if (slot->readPending && slot->readOv && slot->readOv->hEvent) {
            slot->readPending = false;
            slot->lastError = ERROR_OPERATION_ABORTED;
            SetEvent(slot->readOv->hEvent);
        }
        slot->inUse = false;
        slot->hToken = nullptr;
        slot->hStopEvent = nullptr;
        slot->hPacerThread = nullptr;
    }
    LeaveCriticalSection(&g_lock);

    if (!isVirt) {
        return g_origCloseHandle(hObject);
    }

    if (hStop != nullptr) {
        SetEvent(hStop);
    }
    if (hThread != nullptr) {
        WaitForSingleObject(hThread, 500);
        g_origCloseHandle(hThread);
    }
    if (hStop != nullptr) {
        g_origCloseHandle(hStop);
    }
    if (wasStreaming) {
        WriteFeedbackConnected(false);
    }
    return g_origCloseHandle(hObject);
}

// ============================================================================
// In-Process PE Import Address Table (IAT) Patcher (x86 & x64)
// ============================================================================

struct IatHookEntry {
    const char* dllName;
    const char* funcName;
    void*       hookFn;
    void**      origSlot;
};

static IatHookEntry g_hooks[] = {
    { "setupapi.dll", "SetupDiGetClassDevsW",             (void*)&Hook_SetupDiGetClassDevsW,             (void**)&g_origSetupDiGetClassDevsW },
    { "setupapi.dll", "SetupDiEnumDeviceInterfaces",      (void*)&Hook_SetupDiEnumDeviceInterfaces,      (void**)&g_origSetupDiEnumDeviceInterfaces },
    { "setupapi.dll", "SetupDiGetDeviceInterfaceDetailW", (void*)&Hook_SetupDiGetDeviceInterfaceDetailW, (void**)&g_origSetupDiGetDeviceInterfaceDetailW },
    { "setupapi.dll", "SetupDiDestroyDeviceInfoList",     (void*)&Hook_SetupDiDestroyDeviceInfoList,     (void**)&g_origSetupDiDestroyDeviceInfoList },

    { "hid.dll",      "HidD_GetHidGuid",                  (void*)&Hook_HidD_GetHidGuid,                  (void**)&g_origHidD_GetHidGuid },
    { "hid.dll",      "HidD_GetAttributes",               (void*)&Hook_HidD_GetAttributes,               (void**)&g_origHidD_GetAttributes },
    { "hid.dll",      "HidD_GetPreparsedData",            (void*)&Hook_HidD_GetPreparsedData,            (void**)&g_origHidD_GetPreparsedData },
    { "hid.dll",      "HidP_GetCaps",                     (void*)&Hook_HidP_GetCaps,                     (void**)&g_origHidP_GetCaps },
    { "hid.dll",      "HidD_FreePreparsedData",           (void*)&Hook_HidD_FreePreparsedData,           (void**)&g_origHidD_FreePreparsedData },
    { "hid.dll",      "HidD_SetNumInputBuffers",          (void*)&Hook_HidD_SetNumInputBuffers,          (void**)&g_origHidD_SetNumInputBuffers },
    { "hid.dll",      "HidD_GetSerialNumberString",       (void*)&Hook_HidD_GetSerialNumberString,       (void**)&g_origHidD_GetSerialNumberString },
    { "hid.dll",      "HidD_GetFeature",                  (void*)&Hook_HidD_GetFeature,                  (void**)&g_origHidD_GetFeature },

    { "kernel32.dll", "CreateFileW",                      (void*)&Hook_CreateFileW,                      (void**)&g_origCreateFileW },
    { "kernel32.dll", "ReadFile",                         (void*)&Hook_ReadFile,                         (void**)&g_origReadFile },
    { "kernel32.dll", "WriteFile",                        (void*)&Hook_WriteFile,                        (void**)&g_origWriteFile },
    { "kernel32.dll", "GetOverlappedResult",              (void*)&Hook_GetOverlappedResult,              (void**)&g_origGetOverlappedResult },
    { "kernel32.dll", "CancelIoEx",                       (void*)&Hook_CancelIoEx,                       (void**)&g_origCancelIoEx },
    { "kernel32.dll", "CloseHandle",                      (void*)&Hook_CloseHandle,                      (void**)&g_origCloseHandle },
};

static LONG InstallHostIatHooks() {
    HMODULE hExe = GetModuleHandleW(nullptr);
    if (!hExe) return 0;

    uint8_t* base = reinterpret_cast<uint8_t*>(hExe);
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;

    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;

    IMAGE_DATA_DIRECTORY impDir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (impDir.VirtualAddress == 0 || impDir.Size == 0) return 0;

    auto* desc = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + impDir.VirtualAddress);
    LONG patched = 0;

    for (; desc->Name != 0; ++desc) {
        const char* dllName = reinterpret_cast<const char*>(base + desc->Name);
        if (!dllName) continue;

        bool relevantDll = false;
        for (size_t h = 0; h < sizeof(g_hooks) / sizeof(g_hooks[0]); ++h) {
            if (IsSameAsciiIgnoreCase(dllName, g_hooks[h].dllName)) {
                relevantDll = true;
                break;
            }
        }
        if (!relevantDll) continue;

        auto* origThunk = reinterpret_cast<IMAGE_THUNK_DATA*>(
            base + (desc->OriginalFirstThunk ? desc->OriginalFirstThunk : desc->FirstThunk)
        );
        auto* iatThunk = reinterpret_cast<IMAGE_THUNK_DATA*>(base + desc->FirstThunk);

        for (; origThunk->u1.AddressOfData != 0; ++origThunk, ++iatThunk) {
            if (IMAGE_SNAP_BY_ORDINAL(origThunk->u1.Ordinal)) continue;
            auto* byName = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(base + origThunk->u1.AddressOfData);
            const char* fnName = reinterpret_cast<const char*>(byName->Name);

            for (size_t h = 0; h < sizeof(g_hooks) / sizeof(g_hooks[0]); ++h) {
                if (IsSameAsciiIgnoreCase(dllName, g_hooks[h].dllName) &&
                    strcmp(fnName, g_hooks[h].funcName) == 0) {
                    void** slotPtr = reinterpret_cast<void**>(&iatThunk->u1.Function);
                    if (*slotPtr == g_hooks[h].hookFn) {
                        break; // Already hooked
                    }
                    DWORD oldProt = 0;
                    if (VirtualProtect(slotPtr, sizeof(void*), PAGE_READWRITE, &oldProt)) {
                        *g_hooks[h].origSlot = *slotPtr;
                        *slotPtr = g_hooks[h].hookFn;
                        VirtualProtect(slotPtr, sizeof(void*), oldProt, &oldProt);
                        ++patched;
                    }
                    break;
                }
            }
        }
    }

    return patched;
}

extern "C" __declspec(dllexport) int WINAPI LegacyMove_GetHookCount() {
    return (int)g_hookedCount;
}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {
    (void)lpvReserved;
    if (fdwReason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hinstDLL);
        if (!g_lockReady) {
            InitializeCriticalSection(&g_lock);
            g_lockReady = true;
        }
        g_hookedCount = InstallHostIatHooks();
    } else if (fdwReason == DLL_PROCESS_DETACH) {
        if (g_lockReady) {
            EnterCriticalSection(&g_lock);
            if (g_shmView) {
                UnmapViewOfFile(g_shmView);
                g_shmView = nullptr;
            }
            if (g_shmHandle) {
                if (g_origCloseHandle) g_origCloseHandle(g_shmHandle);
                else CloseHandle(g_shmHandle);
                g_shmHandle = nullptr;
            }
            LeaveCriticalSection(&g_lock);
            DeleteCriticalSection(&g_lock);
            g_lockReady = false;
        }
    }
    return TRUE;
}
