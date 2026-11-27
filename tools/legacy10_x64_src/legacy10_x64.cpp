/*
 * Legacy10_x64.dll — 64-bit In-Memory Kinect v1 Proxy for Legacy PSCam Sensor
 *
 * Bridges Legacy PSCam Sensor's lockless seqlock shared-memory channels:
 *   - Local\LegacyWebcamKinectPoseV2  (JDP2, 664 bytes, 1-2 Players)
 *   - Local\LegacyWebcamKinectPose    (JDP1, 344 bytes, 1 Player fallback)
 *   - Local\LegacyWebcamKinectImageV2 (JMI2, 1,305,632 bytes, 640x480 BGRA + 320x240 Player Index Mask)
 *   - Local\LegacyWebcamKinectImage   (JMI1, 1,305,632 bytes, 640x480 BGRA + 320x240 Binary Mask)
 *   - Local\LegacyWebcamKinectCoachX  (JXC1, 28 bytes, Coach X offset)
 *
 * Implements the standard Microsoft Kinect for Windows SDK v1.8 x64 COM ABI
 * (INuiSensor + INuiFrameTexture + global Nui* exports at exact SDK ordinals)
 * for 64-bit UbiArt titles such as Just Dance Legacy Lab (Legacy Lab.exe).
 *
 * Build (zero external runtime DLLs):
 *   python -m ziglang c++ -target x86_64-windows-gnu -shared -O2 -fno-exceptions -fno-rtti \
 *       legacy10_x64.cpp legacy10_x64.def -o ../Legacy10_x64.dll \
 *       -lole32 -loleaut32 -lwinmm -Wl,--enable-stdcall-fixup
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <oleauto.h>
#include <unknwn.h>
#include <stdint.h>
#include <string.h>

// ============================================================================
// Microsoft Kinect for Windows SDK v1.8 x64 Binary ABI Definitions
// ============================================================================

static constexpr HRESULT E_NUI_FRAME_NO_DATA = static_cast<HRESULT>(0x83010001u);

enum NUI_IMAGE_TYPE : int32_t {
    NUI_IMAGE_TYPE_DEPTH_AND_PLAYER_INDEX = 0,
    NUI_IMAGE_TYPE_COLOR                  = 1,
    NUI_IMAGE_TYPE_COLOR_YUV              = 2,
    NUI_IMAGE_TYPE_COLOR_RAW_YUV          = 3,
    NUI_IMAGE_TYPE_DEPTH                  = 4,
    NUI_IMAGE_TYPE_COLOR_INFRARED         = 5,
    NUI_IMAGE_TYPE_COLOR_RAW_BAYER        = 6,
};

enum NUI_IMAGE_RESOLUTION : int32_t {
    NUI_IMAGE_RESOLUTION_INVALID = -1,
    NUI_IMAGE_RESOLUTION_80x60   = 0,
    NUI_IMAGE_RESOLUTION_320x240 = 1,
    NUI_IMAGE_RESOLUTION_640x480 = 2,
    NUI_IMAGE_RESOLUTION_1280x960 = 3,
};

enum NUI_SKELETON_TRACKING_STATE : int32_t {
    NUI_SKELETON_NOT_TRACKED   = 0,
    NUI_SKELETON_POSITION_ONLY = 1,
    NUI_SKELETON_TRACKED       = 2,
};

enum NUI_SKELETON_POSITION_TRACKING_STATE : int32_t {
    NUI_SKELETON_POSITION_NOT_TRACKED = 0,
    NUI_SKELETON_POSITION_INFERRED    = 1,
    NUI_SKELETON_POSITION_TRACKED     = 2,
};

static constexpr int NUI_SKELETON_COUNT          = 6;
static constexpr int NUI_SKELETON_POSITION_COUNT = 20;

#pragma pack(push, 8)
struct Vector4 {
    float x;
    float y;
    float z;
    float w;
};

struct NUI_SURFACE_DESC {
    UINT Width;
    UINT Height;
};

struct NUI_LOCKED_RECT {
    INT   Pitch;
    INT   size;
    BYTE* pBits;
};

struct NUI_IMAGE_VIEW_AREA {
    int  eDigitalZoom;
    LONG lCenterX;
    LONG lCenterY;
};

struct INuiFrameTexture;

struct NUI_IMAGE_FRAME {
    LARGE_INTEGER      liTimeStamp;
    DWORD              dwFrameNumber;
    NUI_IMAGE_TYPE     eImageType;
    NUI_IMAGE_RESOLUTION eResolution;
    INuiFrameTexture*  pFrameTexture;
    DWORD              dwFrameFlags;
    NUI_IMAGE_VIEW_AREA ViewArea;
};

struct NUI_SKELETON_DATA {
    NUI_SKELETON_TRACKING_STATE          eTrackingState;
    DWORD                                dwTrackingID;
    DWORD                                dwEnrollmentIndex;
    DWORD                                dwUserIndex;
    Vector4                              Position;
    Vector4                              SkeletonPositions[NUI_SKELETON_POSITION_COUNT];
    NUI_SKELETON_POSITION_TRACKING_STATE eSkeletonPositionTrackingState[NUI_SKELETON_POSITION_COUNT];
    DWORD                                dwQualityFlags;
};

struct NUI_SKELETON_FRAME {
    LARGE_INTEGER     liTimeStamp;
    DWORD             dwFrameNumber;
    DWORD             dwFlags;
    Vector4           vFloorClipPlane;
    Vector4           vNormalToGravity;
    NUI_SKELETON_DATA SkeletonData[NUI_SKELETON_COUNT];
};

struct NUI_TRANSFORM_SMOOTH_PARAMETERS {
    FLOAT fSmoothing;
    FLOAT fCorrection;
    FLOAT fPrediction;
    FLOAT fJitterRadius;
    FLOAT fMaxDeviationRadius;
};
#pragma pack(pop)

// Compile-time x64 ABI layout guards (Kinect SDK v1.8 x64)
static_assert(sizeof(NUI_LOCKED_RECT) == 16, "NUI_LOCKED_RECT x64 size must be 16");
static_assert(sizeof(NUI_IMAGE_FRAME) == 48, "NUI_IMAGE_FRAME x64 size must be 48");
static_assert(sizeof(NUI_SKELETON_DATA) == 436, "NUI_SKELETON_DATA size must be 436");
static_assert(sizeof(NUI_SKELETON_FRAME) == 2664, "NUI_SKELETON_FRAME size must be 2664");

typedef void (CALLBACK* NuiStatusProc)(HRESULT hrStatus, const OLECHAR* instanceName, const OLECHAR* uniqueDeviceName, void* pUserData);

// Forward COM interfaces
struct INuiAudioBeam;
struct INuiCoordinateMapper;
struct INuiColorCameraSettings;
struct INuiDepthFilter;

// ============================================================================
// Legacy PSCam Sensor Shared Memory Contracts (Exact Match to kinect_shared_memory.py)
// ============================================================================

static constexpr uint32_t MAGIC_JDP1 = 0x3150444Au;  // 'JDP1'
static constexpr uint32_t MAGIC_JDP2 = 0x3250444Au;  // 'JDP2'
static constexpr uint32_t MAGIC_JMI1 = 0x31494D4Au;  // 'JMI1'
static constexpr uint32_t MAGIC_JMI2 = 0x32494D4Au;  // 'JMI2'
static constexpr uint32_t MAGIC_JXC1 = 0x3143584Au;  // 'JXC1'

static constexpr int IPC_COLOR_W = 640;
static constexpr int IPC_COLOR_H = 480;
static constexpr int IPC_MASK_W  = 320;
static constexpr int IPC_MASK_H  = 240;
static constexpr size_t IPC_BGRA_BYTES = IPC_COLOR_W * IPC_COLOR_H * 4;  // 1,228,800
static constexpr size_t IPC_MASK_BYTES = IPC_MASK_W * IPC_MASK_H;        // 76,800

#pragma pack(push, 1)
struct SharedJoint {
    float x;
    float y;
    float z;
    float conf;
};

struct PoseHeader {
    uint32_t magic;
    uint32_t version;
    uint32_t seq;
    uint32_t tracked;  // bool for JDP1; bitmask for JDP2
    uint64_t timestamp_ms;
};

struct PoseBufferV1 {
    PoseHeader  hdr;
    SharedJoint joints[20];
};

struct PoseBufferV2 {
    PoseHeader  hdr;
    SharedJoint players[2][20];
};

struct ImageHeader {
    uint32_t magic;
    uint32_t version;
    uint32_t seq;
    uint32_t tracked;
    uint32_t width;
    uint32_t height;
    uint64_t timestamp_ms;
};

struct ImageBuffer {
    ImageHeader hdr;
    uint8_t     bgra[IPC_BGRA_BYTES];
    uint8_t     mask[IPC_MASK_BYTES];
};

struct CoachXBuffer {
    uint32_t magic;
    uint32_t version;
    uint32_t seq;
    uint32_t enabled;
    float    coach_x;
    uint64_t timestamp_ms;
};
#pragma pack(pop)

static_assert(sizeof(PoseBufferV1) == 344, "JDP1 must be 344 bytes");
static_assert(sizeof(PoseBufferV2) == 664, "JDP2 must be 664 bytes");
static_assert(sizeof(ImageHeader) == 32, "JMI header must be 32 bytes");
static_assert(sizeof(ImageBuffer) == 1305632, "JMI buffer must be 1,305,632 bytes");
static_assert(sizeof(CoachXBuffer) == 28, "JXC1 must be 28 bytes");

// ============================================================================
// Shared Memory Mapping Wrapper (Seqlock Reader)
// ============================================================================

struct ShmChannel {
    HANDLE       hMap         = nullptr;
    const void*  view         = nullptr;
    size_t       expectedSize = 0;
    const wchar_t* name       = nullptr;
    DWORD        lastRetryMs  = 0;

    void init(const wchar_t* mapName, size_t sz) {
        name = mapName;
        expectedSize = sz;
    }

    const void* ensureMapped() {
        if (view) return view;
        DWORD now = GetTickCount();
        if (lastRetryMs != 0 && (now - lastRetryMs) < 250) {
            return nullptr;
        }
        lastRetryMs = now;
        HANDLE h = OpenFileMappingW(FILE_MAP_READ, FALSE, name);
        if (!h) return nullptr;
        void* p = MapViewOfFile(h, FILE_MAP_READ, 0, 0, expectedSize);
        if (!p) {
            CloseHandle(h);
            return nullptr;
        }
        hMap = h;
        view = p;
        return view;
    }

    void close() {
        if (view) {
            UnmapViewOfFile(view);
            view = nullptr;
        }
        if (hMap) {
            CloseHandle(hMap);
            hMap = nullptr;
        }
        lastRetryMs = 0;
    }
};

template <typename T>
static bool readSeqlock(ShmChannel& ch, uint32_t expectedMagic, T& out) {
    const volatile uint8_t* base = static_cast<const volatile uint8_t*>(ch.ensureMapped());
    if (!base) return false;

    const volatile uint32_t* magicPtr = reinterpret_cast<const volatile uint32_t*>(base);
    const volatile uint32_t* seqPtr   = reinterpret_cast<const volatile uint32_t*>(base + 8);

    for (int attempt = 0; attempt < 4; ++attempt) {
        uint32_t s1 = __atomic_load_n(seqPtr, __ATOMIC_ACQUIRE);
        if (s1 & 1u) {
            SwitchToThread();
            continue;
        }
        uint32_t magic = __atomic_load_n(magicPtr, __ATOMIC_RELAXED);
        if (magic != expectedMagic) return false;

        memcpy(&out, const_cast<const void*>(static_cast<const volatile void*>(base)), sizeof(T));

        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        uint32_t s2 = __atomic_load_n(seqPtr, __ATOMIC_ACQUIRE);
        if (s1 == s2) {
            return true;
        }
    }
    return false;
}

static bool readImageChannelSeqlock(
    ShmChannel& ch,
    uint32_t expectedMagic,
    ImageHeader& outHdr,
    uint8_t* outBgra,
    uint8_t* outMask
) {
    const volatile uint8_t* base = static_cast<const volatile uint8_t*>(ch.ensureMapped());
    if (!base) return false;

    const volatile uint32_t* magicPtr = reinterpret_cast<const volatile uint32_t*>(base);
    const volatile uint32_t* seqPtr   = reinterpret_cast<const volatile uint32_t*>(base + 8);

    for (int attempt = 0; attempt < 4; ++attempt) {
        uint32_t s1 = __atomic_load_n(seqPtr, __ATOMIC_ACQUIRE);
        if (s1 & 1u) {
            SwitchToThread();
            continue;
        }
        if (__atomic_load_n(magicPtr, __ATOMIC_RELAXED) != expectedMagic) return false;

        const uint8_t* src = const_cast<const uint8_t*>(base);
        memcpy(&outHdr, src, sizeof(ImageHeader));
        if (outBgra) {
            memcpy(outBgra, src + sizeof(ImageHeader), IPC_BGRA_BYTES);
        }
        if (outMask) {
            memcpy(outMask, src + sizeof(ImageHeader) + IPC_BGRA_BYTES, IPC_MASK_BYTES);
        }

        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        uint32_t s2 = __atomic_load_n(seqPtr, __ATOMIC_ACQUIRE);
        if (s1 == s2) {
            return true;
        }
    }
    return false;
}

// ============================================================================
// INuiFrameTexture COM Implementation (x64)
// ============================================================================

struct INuiFrameTexture : public IUnknown {
    virtual int     STDMETHODCALLTYPE BufferLen() = 0;
    virtual int     STDMETHODCALLTYPE Pitch() = 0;
    virtual HRESULT STDMETHODCALLTYPE LockRect(UINT Level, NUI_LOCKED_RECT* pLockedRect, RECT* pRect, DWORD Flags) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetLevelDesc(UINT Level, NUI_SURFACE_DESC* pDesc) = 0;
    virtual HRESULT STDMETHODCALLTYPE UnlockRect(UINT Level) = 0;
};

class LegacyFrameTexture final : public INuiFrameTexture {
public:
    LegacyFrameTexture(int width, int height, int bpp)
        : m_refCount(1), m_width(width), m_height(height), m_pitch(width * bpp), m_size(width * height * bpp) {
        m_bits = static_cast<BYTE*>(VirtualAlloc(nullptr, m_size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
        if (m_bits) {
            memset(m_bits, 0, m_size);
        }
    }

    ~LegacyFrameTexture() {
        if (m_bits) {
            VirtualFree(m_bits, 0, MEM_RELEASE);
            m_bits = nullptr;
        }
    }

    BYTE* data() { return m_bits; }
    int width() const { return m_width; }
    int height() const { return m_height; }

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppvObject) override {
        if (!ppvObject) return E_POINTER;
        *ppvObject = this;
        AddRef();
        return S_OK;
    }

    ULONG STDMETHODCALLTYPE AddRef() override {
        return static_cast<ULONG>(InterlockedIncrement(&m_refCount));
    }

    ULONG STDMETHODCALLTYPE Release() override {
        ULONG r = static_cast<ULONG>(InterlockedDecrement(&m_refCount));
        if (r == 0) {
            delete this;
        }
        return r;
    }

    int STDMETHODCALLTYPE BufferLen() override { return m_size; }
    int STDMETHODCALLTYPE Pitch() override { return m_pitch; }

    HRESULT STDMETHODCALLTYPE LockRect(UINT /*Level*/, NUI_LOCKED_RECT* pLockedRect, RECT* /*pRect*/, DWORD /*Flags*/) override {
        if (!pLockedRect) return E_POINTER;
        pLockedRect->Pitch = m_pitch;
        pLockedRect->size  = m_size;
        pLockedRect->pBits = m_bits;
        return m_bits ? S_OK : E_OUTOFMEMORY;
    }

    HRESULT STDMETHODCALLTYPE GetLevelDesc(UINT /*Level*/, NUI_SURFACE_DESC* pDesc) override {
        if (!pDesc) return E_POINTER;
        pDesc->Width  = static_cast<UINT>(m_width);
        pDesc->Height = static_cast<UINT>(m_height);
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE UnlockRect(UINT /*Level*/) override {
        return S_OK;
    }

private:
    volatile LONG m_refCount;
    int   m_width;
    int   m_height;
    int   m_pitch;
    int   m_size;
    BYTE* m_bits;
};

// ============================================================================
// INuiSensor COM Interface (Microsoft Kinect SDK v1.8 x64 VTable Order)
// ============================================================================

struct INuiSensor : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE NuiInitialize(DWORD dwFlags) = 0;
    virtual void    STDMETHODCALLTYPE NuiShutdown() = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiSetFrameEndEvent(HANDLE hEvent, DWORD dwFrameEventFlag) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiImageStreamOpen(NUI_IMAGE_TYPE eImageType, NUI_IMAGE_RESOLUTION eResolution, DWORD dwImageFrameFlags, DWORD dwFrameLimit, HANDLE hNextFrameEvent, HANDLE* phStreamHandle) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiImageStreamSetImageFrameFlags(HANDLE hStream, DWORD dwImageFrameFlags) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiImageStreamGetImageFrameFlags(HANDLE hStream, DWORD* pdwImageFrameFlags) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiImageStreamGetNextFrame(HANDLE hStream, DWORD dwMillisecondsToWait, NUI_IMAGE_FRAME* pImageFrame) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiImageStreamReleaseFrame(HANDLE hStream, NUI_IMAGE_FRAME* pImageFrame) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiImageGetColorPixelCoordinatesFromDepthPixel(NUI_IMAGE_RESOLUTION eColorResolution, const NUI_IMAGE_VIEW_AREA* pcViewArea, LONG lDepthX, LONG lDepthY, USHORT usDepthValue, LONG* plColorX, LONG* plColorY) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiImageGetColorPixelCoordinatesFromDepthPixelAtResolution(NUI_IMAGE_RESOLUTION eColorResolution, NUI_IMAGE_RESOLUTION eDepthResolution, const NUI_IMAGE_VIEW_AREA* pcViewArea, LONG lDepthX, LONG lDepthY, USHORT usDepthValue, LONG* plColorX, LONG* plColorY) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiImageGetColorPixelCoordinateFrameFromDepthPixelFrameAtResolution(NUI_IMAGE_RESOLUTION eColorResolution, NUI_IMAGE_RESOLUTION eDepthResolution, DWORD cDepthValues, USHORT* pDepthValues, DWORD cColorCoordinates, LONG* pColorCoordinates) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiCameraElevationSetAngle(LONG lAngleDegrees) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiCameraElevationGetAngle(LONG* plAngleDegrees) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiSkeletonTrackingEnable(HANDLE hNextFrameEvent, DWORD dwFlags) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiSkeletonTrackingDisable() = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiSkeletonSetTrackedSkeletons(DWORD* TrackingIDs) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiSkeletonGetNextFrame(DWORD dwMillisecondsToWait, NUI_SKELETON_FRAME* pSkeletonFrame) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiTransformSmooth(NUI_SKELETON_FRAME* pSkeletonFrame, const NUI_TRANSFORM_SMOOTH_PARAMETERS* pSmoothingParams) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiGetAudioSource(INuiAudioBeam** ppDmo) = 0;
    virtual int     STDMETHODCALLTYPE NuiInstanceIndex() = 0;
    virtual BSTR    STDMETHODCALLTYPE NuiDeviceConnectionId() = 0;
    virtual BSTR    STDMETHODCALLTYPE NuiUniqueKinectId() = 0;
    virtual BSTR    STDMETHODCALLTYPE NuiAudioArrayId() = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiStatus() = 0;
    virtual DWORD   STDMETHODCALLTYPE NuiInitializationFlags() = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiGetCoordinateMapper(INuiCoordinateMapper** pMapping) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiImageFrameGetDepthImagePixelFrameTexture(HANDLE hStream, NUI_IMAGE_FRAME* pImageFrame, BOOL* pNearMode, INuiFrameTexture** ppFrameTexture) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiGetColorCameraSettings(INuiColorCameraSettings** pCameraSettings) = 0;
    virtual BOOL    STDMETHODCALLTYPE NuiGetForceInfraredEmitterOff() = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiSetForceInfraredEmitterOff(BOOL fForceInfraredEmitterOff) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiAccelerometerGetCurrentReading(Vector4* pReading) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiSetDepthFilter(INuiDepthFilter* pDepthFilter) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiGetDepthFilter(INuiDepthFilter** ppDepthFilter) = 0;
    virtual HRESULT STDMETHODCALLTYPE NuiGetDepthFilterForTimeStamp(LARGE_INTEGER liTimeStamp, INuiDepthFilter** ppDepthFilter) = 0;
};

static void resolutionToDims(NUI_IMAGE_RESOLUTION res, int& w, int& h) {
    switch (res) {
        case NUI_IMAGE_RESOLUTION_80x60:    w = 80;   h = 60;  break;
        case NUI_IMAGE_RESOLUTION_320x240:  w = 320;  h = 240; break;
        case NUI_IMAGE_RESOLUTION_640x480:  w = 640;  h = 480; break;
        case NUI_IMAGE_RESOLUTION_1280x960: w = 1280; h = 960; break;
        default:                            w = 320;  h = 240; break;
    }
}

static bool isDepthStreamType(NUI_IMAGE_TYPE t) {
    return t == NUI_IMAGE_TYPE_DEPTH_AND_PLAYER_INDEX || t == NUI_IMAGE_TYPE_DEPTH;
}

static inline NUI_SKELETON_POSITION_TRACKING_STATE confToState(float conf) {
    if (conf >= 0.50f) return NUI_SKELETON_POSITION_TRACKED;
    if (conf >= 0.20f) return NUI_SKELETON_POSITION_INFERRED;
    return NUI_SKELETON_POSITION_NOT_TRACKED;
}

// ============================================================================
// LegacySensor Implementation (Singleton COM Object)
// ============================================================================

struct StreamSlot {
    bool                 active      = false;
    NUI_IMAGE_TYPE       type        = NUI_IMAGE_TYPE_COLOR;
    NUI_IMAGE_RESOLUTION resolution  = NUI_IMAGE_RESOLUTION_640x480;
    DWORD                flags       = 0;
    HANDLE               nextEvent   = nullptr;
    DWORD                frameNumber = 0;
    LegacyFrameTexture*  textures[2] = {nullptr, nullptr};
    int                  texIndex    = 0;
};

class LegacyKinectSensor final : public INuiSensor {
public:
    LegacyKinectSensor() : m_refCount(1) {
        InitializeCriticalSection(&m_cs);
        m_startTickMs = GetTickCount64();
        m_connId   = SysAllocString(L"USB\\VID_045E&PID_02AE\\LEGACYPSCAM001");
        m_uniqueId = SysAllocString(L"LEGACYPSCAM001");
        m_audioId  = SysAllocString(L"LEGACYPSCAM_AUDIO001");

        m_shmPoseV1.init(L"Local\\LegacyWebcamKinectPose", sizeof(PoseBufferV1));
        m_shmPoseV2.init(L"Local\\LegacyWebcamKinectPoseV2", sizeof(PoseBufferV2));
        m_shmImgV1.init(L"Local\\LegacyWebcamKinectImage", sizeof(ImageBuffer));
        m_shmImgV2.init(L"Local\\LegacyWebcamKinectImageV2", sizeof(ImageBuffer));
        m_shmCoachX.init(L"Local\\LegacyWebcamKinectCoachX", sizeof(CoachXBuffer));

        m_tmpBgra = static_cast<uint8_t*>(VirtualAlloc(nullptr, IPC_BGRA_BYTES, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
        m_tmpMask = static_cast<uint8_t*>(VirtualAlloc(nullptr, IPC_MASK_BYTES, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    }

    ~LegacyKinectSensor() {
        NuiShutdown();
        if (m_tmpBgra) VirtualFree(m_tmpBgra, 0, MEM_RELEASE);
        if (m_tmpMask) VirtualFree(m_tmpMask, 0, MEM_RELEASE);
        if (m_connId) SysFreeString(m_connId);
        if (m_uniqueId) SysFreeString(m_uniqueId);
        if (m_audioId) SysFreeString(m_audioId);
        DeleteCriticalSection(&m_cs);
    }

    // IUnknown
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID /*riid*/, void** ppvObject) override {
        if (!ppvObject) return E_POINTER;
        *ppvObject = this;
        AddRef();
        return S_OK;
    }

    ULONG STDMETHODCALLTYPE AddRef() override {
        return static_cast<ULONG>(InterlockedIncrement(&m_refCount));
    }

    ULONG STDMETHODCALLTYPE Release() override {
        // Keep singleton alive for the lifetime of the host process to match Kinect10 safety
        LONG r = InterlockedDecrement(&m_refCount);
        if (r < 1) {
            InterlockedExchange(&m_refCount, 1);
            return 1;
        }
        return static_cast<ULONG>(r);
    }

    // INuiSensor
    HRESULT STDMETHODCALLTYPE NuiInitialize(DWORD dwFlags) override {
        EnterCriticalSection(&m_cs);
        m_initFlags = dwFlags;
        m_initialized = true;
        if (!m_pacerRunning) {
            m_pacerRunning = true;
            m_pacerThread = CreateThread(nullptr, 0, &LegacyKinectSensor::pacerThreadProc, this, 0, nullptr);
        }
        LeaveCriticalSection(&m_cs);
        return S_OK;
    }

    void STDMETHODCALLTYPE NuiShutdown() override {
        HANDLE hThread = nullptr;
        EnterCriticalSection(&m_cs);
        m_initialized = false;
        m_pacerRunning = false;
        hThread = m_pacerThread;
        m_pacerThread = nullptr;
        m_skelEvent = nullptr;
        m_frameEndEvent = nullptr;
        for (int i = 0; i < MAX_STREAMS; ++i) {
            m_streams[i].active = false;
            m_streams[i].nextEvent = nullptr;
            for (int t = 0; t < 2; ++t) {
                if (m_streams[i].textures[t]) {
                    m_streams[i].textures[t]->Release();
                    m_streams[i].textures[t] = nullptr;
                }
            }
        }
        LeaveCriticalSection(&m_cs);

        if (hThread) {
            WaitForSingleObject(hThread, 1500);
            CloseHandle(hThread);
        }

        m_shmPoseV1.close();
        m_shmPoseV2.close();
        m_shmImgV1.close();
        m_shmImgV2.close();
        m_shmCoachX.close();
    }

    HRESULT STDMETHODCALLTYPE NuiSetFrameEndEvent(HANDLE hEvent, DWORD /*dwFrameEventFlag*/) override {
        EnterCriticalSection(&m_cs);
        m_frameEndEvent = hEvent;
        LeaveCriticalSection(&m_cs);
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiImageStreamOpen(
        NUI_IMAGE_TYPE eImageType,
        NUI_IMAGE_RESOLUTION eResolution,
        DWORD dwImageFrameFlags,
        DWORD /*dwFrameLimit*/,
        HANDLE hNextFrameEvent,
        HANDLE* phStreamHandle
    ) override {
        if (!phStreamHandle) return E_POINTER;
        EnterCriticalSection(&m_cs);
        int slotIdx = -1;
        for (int i = 0; i < MAX_STREAMS; ++i) {
            if (!m_streams[i].active) {
                slotIdx = i;
                break;
            }
        }
        if (slotIdx < 0) {
            LeaveCriticalSection(&m_cs);
            return E_FAIL;
        }

        int w = 640, h = 480;
        resolutionToDims(eResolution, w, h);
        int bpp = isDepthStreamType(eImageType) ? 2 : 4;

        StreamSlot& st = m_streams[slotIdx];
        st.active      = true;
        st.type        = eImageType;
        st.resolution  = eResolution;
        st.flags       = dwImageFrameFlags;
        st.nextEvent   = hNextFrameEvent;
        st.frameNumber = 0;
        st.texIndex    = 0;
        for (int t = 0; t < 2; ++t) {
            if (st.textures[t]) st.textures[t]->Release();
            st.textures[t] = new LegacyFrameTexture(w, h, bpp);
        }

        if (!m_pacerRunning) {
            m_pacerRunning = true;
            m_pacerThread = CreateThread(nullptr, 0, &LegacyKinectSensor::pacerThreadProc, this, 0, nullptr);
        }

        *phStreamHandle = reinterpret_cast<HANDLE>(static_cast<uintptr_t>(0x1000u + slotIdx));
        LeaveCriticalSection(&m_cs);
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiImageStreamSetImageFrameFlags(HANDLE hStream, DWORD dwImageFrameFlags) override {
        int idx = streamHandleToIndex(hStream);
        if (idx < 0) return E_INVALIDARG;
        EnterCriticalSection(&m_cs);
        m_streams[idx].flags = dwImageFrameFlags;
        LeaveCriticalSection(&m_cs);
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiImageStreamGetImageFrameFlags(HANDLE hStream, DWORD* pdwImageFrameFlags) override {
        if (!pdwImageFrameFlags) return E_POINTER;
        int idx = streamHandleToIndex(hStream);
        if (idx < 0) return E_INVALIDARG;
        EnterCriticalSection(&m_cs);
        *pdwImageFrameFlags = m_streams[idx].flags;
        LeaveCriticalSection(&m_cs);
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiImageStreamGetNextFrame(
        HANDLE hStream,
        DWORD /*dwMillisecondsToWait*/,
        NUI_IMAGE_FRAME* pImageFrame
    ) override {
        if (!pImageFrame) return E_POINTER;
        int idx = streamHandleToIndex(hStream);
        if (idx < 0) return E_INVALIDARG;

        EnterCriticalSection(&m_cs);
        StreamSlot& st = m_streams[idx];
        if (!st.active) {
            LeaveCriticalSection(&m_cs);
            return E_FAIL;
        }
        // Reset manual-reset stream event so WaitForSingleObject paces strictly at 30 FPS (matches Kinect10.dll)
        if (st.nextEvent) {
            ResetEvent(st.nextEvent);
        }
        DWORD frameNum = ++st.frameNumber;

        LegacyFrameTexture* tex = st.textures[st.texIndex];
        st.texIndex ^= 1;
        if (!tex || !tex->data()) {
            LeaveCriticalSection(&m_cs);
            return E_OUTOFMEMORY;
        }

        fillStreamTexture(st, tex);

        memset(pImageFrame, 0, sizeof(NUI_IMAGE_FRAME));
        pImageFrame->liTimeStamp.QuadPart  = static_cast<LONGLONG>(GetTickCount64() - m_startTickMs);
        pImageFrame->dwFrameNumber         = frameNum;
        pImageFrame->eImageType            = st.type;
        pImageFrame->eResolution           = st.resolution;
        pImageFrame->pFrameTexture         = tex;
        pImageFrame->dwFrameFlags          = st.flags;
        pImageFrame->ViewArea.eDigitalZoom = 0;
        pImageFrame->ViewArea.lCenterX     = 0;
        pImageFrame->ViewArea.lCenterY     = 0;
        LeaveCriticalSection(&m_cs);
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiImageStreamReleaseFrame(HANDLE /*hStream*/, NUI_IMAGE_FRAME* /*pImageFrame*/) override {
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiImageGetColorPixelCoordinatesFromDepthPixel(
        NUI_IMAGE_RESOLUTION eColorResolution,
        const NUI_IMAGE_VIEW_AREA* pcViewArea,
        LONG lDepthX,
        LONG lDepthY,
        USHORT usDepthValue,
        LONG* plColorX,
        LONG* plColorY
    ) override {
        return NuiImageGetColorPixelCoordinatesFromDepthPixelAtResolution(
            eColorResolution, NUI_IMAGE_RESOLUTION_320x240, pcViewArea, lDepthX, lDepthY, usDepthValue, plColorX, plColorY
        );
    }

    HRESULT STDMETHODCALLTYPE NuiImageGetColorPixelCoordinatesFromDepthPixelAtResolution(
        NUI_IMAGE_RESOLUTION eColorResolution,
        NUI_IMAGE_RESOLUTION eDepthResolution,
        const NUI_IMAGE_VIEW_AREA* /*pcViewArea*/,
        LONG lDepthX,
        LONG lDepthY,
        USHORT /*usDepthValue*/,
        LONG* plColorX,
        LONG* plColorY
    ) override {
        int cw = 640, ch = 480, dw = 320, dh = 240;
        resolutionToDims(eColorResolution, cw, ch);
        resolutionToDims(eDepthResolution, dw, dh);
        if (dw <= 0) dw = 320;
        if (dh <= 0) dh = 240;
        LONG cx = (cw == dw * 2) ? (lDepthX << 1) : ((lDepthX * cw) / dw);
        LONG cy = (ch == dh * 2) ? (lDepthY << 1) : ((lDepthY * ch) / dh);
        if (cx < 0) cx = 0; else if (cx >= cw) cx = cw - 1;
        if (cy < 0) cy = 0; else if (cy >= ch) cy = ch - 1;
        if (plColorX) *plColorX = cx;
        if (plColorY) *plColorY = cy;
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiImageGetColorPixelCoordinateFrameFromDepthPixelFrameAtResolution(
        NUI_IMAGE_RESOLUTION eColorResolution,
        NUI_IMAGE_RESOLUTION eDepthResolution,
        DWORD cDepthValues,
        USHORT* /*pDepthValues*/,
        DWORD cColorCoordinates,
        LONG* pColorCoordinates
    ) override {
        if (!pColorCoordinates) return E_POINTER;
        int cw = 640, ch = 480, dw = 320, dh = 240;
        resolutionToDims(eColorResolution, cw, ch);
        resolutionToDims(eDepthResolution, dw, dh);
        DWORD count = cDepthValues;
        if (cColorCoordinates / 2 < count) count = cColorCoordinates / 2;
        for (DWORD i = 0; i < count; ++i) {
            LONG dx = static_cast<LONG>(i % static_cast<DWORD>(dw));
            LONG dy = static_cast<LONG>(i / static_cast<DWORD>(dw));
            pColorCoordinates[i * 2]     = (dx * cw) / dw;
            pColorCoordinates[i * 2 + 1] = (dy * ch) / dh;
        }
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiCameraElevationSetAngle(LONG lAngleDegrees) override {
        if (lAngleDegrees < -27) lAngleDegrees = -27;
        if (lAngleDegrees > 27) lAngleDegrees = 27;
        m_elevation = lAngleDegrees;
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiCameraElevationGetAngle(LONG* plAngleDegrees) override {
        if (!plAngleDegrees) return E_POINTER;
        *plAngleDegrees = m_elevation;
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiSkeletonTrackingEnable(HANDLE hNextFrameEvent, DWORD dwFlags) override {
        EnterCriticalSection(&m_cs);
        m_skelEvent = hNextFrameEvent;
        m_skelFlags = dwFlags;
        if (!m_pacerRunning) {
            m_pacerRunning = true;
            m_pacerThread = CreateThread(nullptr, 0, &LegacyKinectSensor::pacerThreadProc, this, 0, nullptr);
        }
        LeaveCriticalSection(&m_cs);
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiSkeletonTrackingDisable() override {
        EnterCriticalSection(&m_cs);
        m_skelEvent = nullptr;
        LeaveCriticalSection(&m_cs);
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiSkeletonSetTrackedSkeletons(DWORD* /*TrackingIDs*/) override {
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiSkeletonGetNextFrame(
        DWORD /*dwMillisecondsToWait*/,
        NUI_SKELETON_FRAME* pSkeletonFrame
    ) override {
        if (!pSkeletonFrame) return E_POINTER;

        // Reset manual-reset skeleton event (CRITICAL: UbiArt waits on hNextSkeletonEvent;
        // without ResetEvent the game thread busy-spins at 1000 Hz and destroys move timing/scoring)
        HANDLE hSkelEv = nullptr;
        EnterCriticalSection(&m_cs);
        hSkelEv = m_skelEvent;
        LeaveCriticalSection(&m_cs);
        if (hSkelEv) {
            ResetEvent(hSkelEv);
        }

        DWORD frameNum = static_cast<DWORD>(InterlockedIncrement(&m_skelFrameNumber));

        memset(pSkeletonFrame, 0, sizeof(NUI_SKELETON_FRAME));
        pSkeletonFrame->liTimeStamp.QuadPart = static_cast<LONGLONG>(GetTickCount64() - m_startTickMs);
        pSkeletonFrame->dwFrameNumber        = frameNum;
        pSkeletonFrame->dwFlags              = 0;
        // Exact Kinect v1.8 & Legacy10.dll convention: floor plane normal +Y (D=0), gravity vector -Y
        pSkeletonFrame->vFloorClipPlane      = {0.0f,  1.0f, 0.0f, 0.0f};
        pSkeletonFrame->vNormalToGravity     = {0.0f, -1.0f, 0.0f, 0.0f};

        // Optional CoachX offset (disabled by default in Legacy PSCam Sensor)
        float coachOffsetX = 0.0f;
        CoachXBuffer cxBuf{};
        if (readSeqlock(m_shmCoachX, MAGIC_JXC1, cxBuf) && cxBuf.enabled != 0) {
            coachOffsetX = cxBuf.coach_x;
        }

        // Prefer JDP2 (1-2 Players) and fall back cleanly to JDP1 (1 Player)
        PoseBufferV2 v2{};
        if (readSeqlock(m_shmPoseV2, MAGIC_JDP2, v2)) {
            uint32_t mask = v2.hdr.tracked;
            for (int p = 0; p < 2; ++p) {
                if (mask & (1u << p)) {
                    populateSkeletonSlot(pSkeletonFrame->SkeletonData[p], p, v2.players[p], coachOffsetX);
                }
            }
            return S_OK;
        }

        PoseBufferV1 v1{};
        if (readSeqlock(m_shmPoseV1, MAGIC_JDP1, v1) && v1.hdr.tracked != 0) {
            populateSkeletonSlot(pSkeletonFrame->SkeletonData[0], 0, v1.joints, coachOffsetX);
            return S_OK;
        }

        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiTransformSmooth(
        NUI_SKELETON_FRAME* /*pSkeletonFrame*/,
        const NUI_TRANSFORM_SMOOTH_PARAMETERS* /*pSmoothingParams*/
    ) override {
        // Adaptive dynamic EMA smoothing is already applied by PoseTracker
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiGetAudioSource(INuiAudioBeam** ppDmo) override {
        if (ppDmo) *ppDmo = nullptr;
        return E_NOTIMPL;
    }

    int STDMETHODCALLTYPE NuiInstanceIndex() override { return 0; }
    BSTR STDMETHODCALLTYPE NuiDeviceConnectionId() override { return m_connId; }
    BSTR STDMETHODCALLTYPE NuiUniqueKinectId() override { return m_uniqueId; }
    BSTR STDMETHODCALLTYPE NuiAudioArrayId() override { return m_audioId; }
    HRESULT STDMETHODCALLTYPE NuiStatus() override { return S_OK; }
    DWORD STDMETHODCALLTYPE NuiInitializationFlags() override { return m_initFlags; }

    HRESULT STDMETHODCALLTYPE NuiGetCoordinateMapper(INuiCoordinateMapper** pMapping) override {
        if (pMapping) *pMapping = nullptr;
        return E_NOTIMPL;
    }

    HRESULT STDMETHODCALLTYPE NuiImageFrameGetDepthImagePixelFrameTexture(
        HANDLE /*hStream*/,
        NUI_IMAGE_FRAME* pImageFrame,
        BOOL* pNearMode,
        INuiFrameTexture** ppFrameTexture
    ) override {
        if (pNearMode) *pNearMode = FALSE;
        if (!ppFrameTexture) return E_POINTER;
        if (pImageFrame && pImageFrame->pFrameTexture) {
            pImageFrame->pFrameTexture->AddRef();
            *ppFrameTexture = pImageFrame->pFrameTexture;
            return S_OK;
        }
        *ppFrameTexture = nullptr;
        return E_FAIL;
    }

    HRESULT STDMETHODCALLTYPE NuiGetColorCameraSettings(INuiColorCameraSettings** pCameraSettings) override {
        if (pCameraSettings) *pCameraSettings = nullptr;
        return E_NOTIMPL;
    }

    BOOL STDMETHODCALLTYPE NuiGetForceInfraredEmitterOff() override { return FALSE; }
    HRESULT STDMETHODCALLTYPE NuiSetForceInfraredEmitterOff(BOOL /*fForce*/) override { return S_OK; }

    HRESULT STDMETHODCALLTYPE NuiAccelerometerGetCurrentReading(Vector4* pReading) override {
        if (!pReading) return E_POINTER;
        *pReading = {0.0f, -1.0f, 0.0f, 0.0f};
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE NuiSetDepthFilter(INuiDepthFilter* /*pDepthFilter*/) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE NuiGetDepthFilter(INuiDepthFilter** ppDepthFilter) override {
        if (ppDepthFilter) *ppDepthFilter = nullptr;
        return E_NOTIMPL;
    }
    HRESULT STDMETHODCALLTYPE NuiGetDepthFilterForTimeStamp(LARGE_INTEGER /*liTimeStamp*/, INuiDepthFilter** ppDepthFilter) override {
        if (ppDepthFilter) *ppDepthFilter = nullptr;
        return E_NOTIMPL;
    }

private:
    static constexpr int MAX_STREAMS = 4;

    int streamHandleToIndex(HANDLE hStream) const {
        uintptr_t v = reinterpret_cast<uintptr_t>(hStream);
        if (v < 0x1000u || v >= 0x1000u + MAX_STREAMS) return -1;
        return static_cast<int>(v - 0x1000u);
    }

    static void populateSkeletonSlot(
        NUI_SKELETON_DATA& dst,
        int slotIdx,
        const SharedJoint joints[20],
        float coachOffsetX
    ) {
        dst.eTrackingState    = NUI_SKELETON_TRACKED;
        dst.dwTrackingID      = static_cast<DWORD>(1 + slotIdx);
        dst.dwEnrollmentIndex = 0;
        dst.dwUserIndex       = static_cast<DWORD>(1 + slotIdx);
        dst.dwQualityFlags    = 0;

        float hipX = joints[0].x + coachOffsetX;
        float hipY = joints[0].y;
        float hipZ = (joints[0].z > 0.2f) ? joints[0].z : 2.0f;
        dst.Position = {hipX, hipY, hipZ, 1.0f};

        for (int j = 0; j < NUI_SKELETON_POSITION_COUNT; ++j) {
            float z = (joints[j].z > 0.2f) ? joints[j].z : hipZ;
            dst.SkeletonPositions[j] = {joints[j].x + coachOffsetX, joints[j].y, z, 1.0f};
            dst.eSkeletonPositionTrackingState[j] = confToState(joints[j].conf);
        }
    }

    void fillStreamTexture(const StreamSlot& st, LegacyFrameTexture* tex) {
        int outW = tex->width();
        int outH = tex->height();
        BYTE* dst = tex->data();

        ImageHeader hdr{};
        bool isV2 = false;
        bool hasImg = false;
        if (m_tmpBgra && m_tmpMask) {
            if (isDepthStreamType(st.type)) {
                hasImg = readImageChannelSeqlock(m_shmImgV2, MAGIC_JMI2, hdr, nullptr, m_tmpMask);
                if (hasImg) {
                    isV2 = true;
                } else {
                    hasImg = readImageChannelSeqlock(m_shmImgV1, MAGIC_JMI1, hdr, nullptr, m_tmpMask);
                }
            } else {
                hasImg = readImageChannelSeqlock(m_shmImgV2, MAGIC_JMI2, hdr, m_tmpBgra, nullptr);
                if (!hasImg) {
                    hasImg = readImageChannelSeqlock(m_shmImgV1, MAGIC_JMI1, hdr, m_tmpBgra, nullptr);
                }
            }
        }

        if (!isDepthStreamType(st.type)) {
            // Color BGRA stream
            if (!hasImg || !m_tmpBgra) {
                memset(dst, 0, static_cast<size_t>(tex->BufferLen()));
                return;
            }
            if (outW == IPC_COLOR_W && outH == IPC_COLOR_H) {
                memcpy(dst, m_tmpBgra, IPC_BGRA_BYTES);
            } else {
                uint32_t* dst32 = reinterpret_cast<uint32_t*>(dst);
                const uint32_t* src32 = reinterpret_cast<const uint32_t*>(m_tmpBgra);
                for (int y = 0; y < outH; ++y) {
                    int sy = (y * IPC_COLOR_H) / outH;
                    const uint32_t* srow = src32 + sy * IPC_COLOR_W;
                    uint32_t* drow = dst32 + y * outW;
                    for (int x = 0; x < outW; ++x) {
                        int sx = (x * IPC_COLOR_W) / outW;
                        drow[x] = srow[sx];
                    }
                }
            }
            return;
        }

        // Depth / Depth+PlayerIndex stream (16-bit: (depth_mm << 3) | player_index)
        uint16_t* dst16 = reinterpret_cast<uint16_t*>(dst);
        if (!hasImg || !m_tmpMask || hdr.tracked == 0) {
            memset(dst16, 0, static_cast<size_t>(outW * outH) * sizeof(uint16_t));
            return;
        }

        const bool includePlayerIdx = (st.type == NUI_IMAGE_TYPE_DEPTH_AND_PLAYER_INDEX);
        const uint16_t baseDepthShifted = static_cast<uint16_t>(2200u << 3);

        if (outW == IPC_MASK_W && outH == IPC_MASK_H) {
            for (int i = 0; i < IPC_MASK_W * IPC_MASK_H; ++i) {
                uint8_t m = m_tmpMask[i];
                uint16_t pidx = 0;
                if (isV2) {
                    if (m >= 1 && m <= 6) pidx = m;
                } else {
                    if (m >= 0x40) pidx = 1;
                }
                if (pidx > 0) {
                    dst16[i] = includePlayerIdx ? static_cast<uint16_t>(baseDepthShifted | pidx) : baseDepthShifted;
                } else {
                    dst16[i] = 0;
                }
            }
        } else {
            for (int y = 0; y < outH; ++y) {
                int sy = (y * IPC_MASK_H) / outH;
                const uint8_t* srow = m_tmpMask + sy * IPC_MASK_W;
                uint16_t* drow = dst16 + y * outW;
                for (int x = 0; x < outW; ++x) {
                    int sx = (x * IPC_MASK_W) / outW;
                    uint8_t m = srow[sx];
                    uint16_t pidx = isV2 ? ((m >= 1 && m <= 6) ? m : 0) : ((m >= 0x40) ? 1 : 0);
                    drow[x] = (pidx > 0)
                        ? (includePlayerIdx ? static_cast<uint16_t>(baseDepthShifted | pidx) : baseDepthShifted)
                        : 0;
                }
            }
        }
    }

    static DWORD WINAPI pacerThreadProc(LPVOID param) {
        LegacyKinectSensor* self = static_cast<LegacyKinectSensor*>(param);
        // 30 FPS standard Kinect v1 pacer (33 ms) — required by Just Dance scoring engine
        timeBeginPeriod(1);
        while (self->m_pacerRunning) {
            Sleep(33);
            if (!self->m_pacerRunning) break;
            InterlockedIncrement(&self->m_frameCounter);

            EnterCriticalSection(&self->m_cs);
            for (int i = 0; i < MAX_STREAMS; ++i) {
                if (self->m_streams[i].active && self->m_streams[i].nextEvent) {
                    SetEvent(self->m_streams[i].nextEvent);
                }
            }
            if (self->m_skelEvent) {
                SetEvent(self->m_skelEvent);
            }
            if (self->m_frameEndEvent) {
                SetEvent(self->m_frameEndEvent);
            }
            LeaveCriticalSection(&self->m_cs);
        }
        timeEndPeriod(1);
        return 0;
    }

    volatile LONG     m_refCount;
    CRITICAL_SECTION  m_cs;
    volatile bool     m_initialized     = false;
    volatile bool     m_pacerRunning    = false;
    HANDLE            m_pacerThread     = nullptr;
    HANDLE            m_skelEvent       = nullptr;
    HANDLE            m_frameEndEvent   = nullptr;
    DWORD             m_initFlags       = 0;
    DWORD             m_skelFlags       = 0;
    LONG              m_elevation       = 0;
    volatile LONG     m_frameCounter    = 0;
    volatile LONG     m_skelFrameNumber = 0;
    ULONGLONG         m_startTickMs     = 0;

    BSTR m_connId   = nullptr;
    BSTR m_uniqueId = nullptr;
    BSTR m_audioId  = nullptr;

    StreamSlot m_streams[MAX_STREAMS];
    ShmChannel m_shmPoseV1;
    ShmChannel m_shmPoseV2;
    ShmChannel m_shmImgV1;
    ShmChannel m_shmImgV2;
    ShmChannel m_shmCoachX;

    uint8_t* m_tmpBgra = nullptr;
    uint8_t* m_tmpMask = nullptr;
};

// ============================================================================
// Global Singleton & Kinect10.dll C API Exports (Exact SDK Ordinals)
// ============================================================================

static LegacyKinectSensor* g_sensor = nullptr;
static CRITICAL_SECTION    g_globalCs;
static bool                g_globalCsInit = false;
static NuiStatusProc       g_statusCallback = nullptr;
static void*               g_statusUserData = nullptr;

static LegacyKinectSensor* getSensor() {
    EnterCriticalSection(&g_globalCs);
    if (!g_sensor) {
        g_sensor = new LegacyKinectSensor();
    }
    LegacyKinectSensor* s = g_sensor;
    LeaveCriticalSection(&g_globalCs);
    return s;
}

extern "C" {

HRESULT WINAPI NuiGetSensorCount(int* pCount) {
    if (!pCount) return E_POINTER;
    *pCount = 1;
    return S_OK;
}

HRESULT WINAPI NuiCreateSensorByIndex(int index, INuiSensor** ppNuiSensor) {
    if (!ppNuiSensor) return E_POINTER;
    if (index != 0) {
        *ppNuiSensor = nullptr;
        return E_INVALIDARG;
    }
    LegacyKinectSensor* s = getSensor();
    s->AddRef();
    *ppNuiSensor = s;
    return S_OK;
}

HRESULT WINAPI NuiCreateSensorById(const OLECHAR* /*strInstanceId*/, INuiSensor** ppNuiSensor) {
    return NuiCreateSensorByIndex(0, ppNuiSensor);
}

void WINAPI NuiSetDeviceStatusCallback(NuiStatusProc callback, void* pUserData) {
    EnterCriticalSection(&g_globalCs);
    g_statusCallback = callback;
    g_statusUserData = pUserData;
    LeaveCriticalSection(&g_globalCs);
}

HRESULT WINAPI NuiInitialize(DWORD dwFlags) {
    return getSensor()->NuiInitialize(dwFlags);
}

void WINAPI NuiShutdown() {
    if (g_sensor) {
        g_sensor->NuiShutdown();
    }
}

HRESULT WINAPI NuiSetFrameEndEvent(HANDLE hEvent, DWORD dwFrameEventFlag) {
    return getSensor()->NuiSetFrameEndEvent(hEvent, dwFrameEventFlag);
}

HRESULT WINAPI NuiImageStreamOpen(
    NUI_IMAGE_TYPE eImageType,
    NUI_IMAGE_RESOLUTION eResolution,
    DWORD dwImageFrameFlags,
    DWORD dwFrameLimit,
    HANDLE hNextFrameEvent,
    HANDLE* phStreamHandle
) {
    return getSensor()->NuiImageStreamOpen(
        eImageType, eResolution, dwImageFrameFlags, dwFrameLimit, hNextFrameEvent, phStreamHandle
    );
}

HRESULT WINAPI NuiImageStreamSetImageFrameFlags(HANDLE hStream, DWORD dwImageFrameFlags) {
    return getSensor()->NuiImageStreamSetImageFrameFlags(hStream, dwImageFrameFlags);
}

HRESULT WINAPI NuiImageStreamGetImageFrameFlags(HANDLE hStream, DWORD* pdwImageFrameFlags) {
    return getSensor()->NuiImageStreamGetImageFrameFlags(hStream, pdwImageFrameFlags);
}

HRESULT WINAPI NuiImageStreamGetNextFrame(
    HANDLE hStream,
    DWORD dwMillisecondsToWait,
    NUI_IMAGE_FRAME* pImageFrame
) {
    return getSensor()->NuiImageStreamGetNextFrame(hStream, dwMillisecondsToWait, pImageFrame);
}

HRESULT WINAPI NuiImageStreamReleaseFrame(HANDLE hStream, NUI_IMAGE_FRAME* pImageFrame) {
    return getSensor()->NuiImageStreamReleaseFrame(hStream, pImageFrame);
}

HRESULT WINAPI NuiImageGetColorPixelCoordinatesFromDepthPixel(
    NUI_IMAGE_RESOLUTION eColorResolution,
    const NUI_IMAGE_VIEW_AREA* pcViewArea,
    LONG lDepthX,
    LONG lDepthY,
    USHORT usDepthValue,
    LONG* plColorX,
    LONG* plColorY
) {
    return getSensor()->NuiImageGetColorPixelCoordinatesFromDepthPixel(
        eColorResolution, pcViewArea, lDepthX, lDepthY, usDepthValue, plColorX, plColorY
    );
}

HRESULT WINAPI NuiImageGetColorPixelCoordinatesFromDepthPixelAtResolution(
    NUI_IMAGE_RESOLUTION eColorResolution,
    NUI_IMAGE_RESOLUTION eDepthResolution,
    const NUI_IMAGE_VIEW_AREA* pcViewArea,
    LONG lDepthX,
    LONG lDepthY,
    USHORT usDepthValue,
    LONG* plColorX,
    LONG* plColorY
) {
    return getSensor()->NuiImageGetColorPixelCoordinatesFromDepthPixelAtResolution(
        eColorResolution, eDepthResolution, pcViewArea, lDepthX, lDepthY, usDepthValue, plColorX, plColorY
    );
}

HRESULT WINAPI NuiCameraElevationGetAngle(LONG* plAngleDegrees) {
    return getSensor()->NuiCameraElevationGetAngle(plAngleDegrees);
}

HRESULT WINAPI NuiCameraElevationSetAngle(LONG lAngleDegrees) {
    return getSensor()->NuiCameraElevationSetAngle(lAngleDegrees);
}

HRESULT WINAPI NuiSkeletonTrackingEnable(HANDLE hNextFrameEvent, DWORD dwFlags) {
    return getSensor()->NuiSkeletonTrackingEnable(hNextFrameEvent, dwFlags);
}

HRESULT WINAPI NuiSkeletonTrackingDisable() {
    return getSensor()->NuiSkeletonTrackingDisable();
}

HRESULT WINAPI NuiSkeletonSetTrackedSkeletons(DWORD* TrackingIDs) {
    return getSensor()->NuiSkeletonSetTrackedSkeletons(TrackingIDs);
}

HRESULT WINAPI NuiSkeletonGetNextFrame(DWORD dwMillisecondsToWait, NUI_SKELETON_FRAME* pSkeletonFrame) {
    return getSensor()->NuiSkeletonGetNextFrame(dwMillisecondsToWait, pSkeletonFrame);
}

HRESULT WINAPI NuiTransformSmooth(
    NUI_SKELETON_FRAME* pSkeletonFrame,
    const NUI_TRANSFORM_SMOOTH_PARAMETERS* pSmoothingParams
) {
    return getSensor()->NuiTransformSmooth(pSkeletonFrame, pSmoothingParams);
}

BOOL WINAPI DllMain(HINSTANCE /*hinstDLL*/, DWORD fdwReason, LPVOID /*lpvReserved*/) {
    if (fdwReason == DLL_PROCESS_ATTACH) {
        if (!g_globalCsInit) {
            InitializeCriticalSection(&g_globalCs);
            g_globalCsInit = true;
        }
    } else if (fdwReason == DLL_PROCESS_DETACH) {
        if (g_sensor) {
            g_sensor->NuiShutdown();
        }
    }
    return TRUE;
}

}  // extern "C"
