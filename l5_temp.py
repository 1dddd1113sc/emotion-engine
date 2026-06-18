"""L5 温度采集 — 通过 LibreHardwareMonitor DLL 直连"""
import sys

_LHM_DIR = r'C:\Users\Daniel Wu\AppData\Local\Microsoft\WinGet\Packages\LibreHardwareMonitor.LibreHardwareMonitor_Microsoft.Winget.Source_8wekyb3d8bbwe'

_initialized = False
_computer = None


def _init():
    global _initialized, _computer
    if _initialized:
        return
    try:
        import clr
        sys.path.append(_LHM_DIR)
        clr.AddReference('LibreHardwareMonitorLib')
        from LibreHardwareMonitor.Hardware import Computer

        _computer = Computer()
        _computer.IsCpuEnabled = True
        _computer.IsGpuEnabled = True
        _computer.IsMemoryEnabled = True
        _computer.Open()
        _initialized = True
    except Exception:
        _initialized = True  # 标记已尝试，不重复初始化


def read_temperatures() -> dict:
    """
    读取温度数据。
    返回: {
        'cpu_temp': float|None,      # CPU 温度 (°C)，非管理员返回 None
        'gpu_temp': float|None,      # GPU 核心温度 (°C)
        'gpu_hotspot': float|None,   # GPU 热点温度 (°C)
    }
    """
    _init()
    if not _computer:
        return {'cpu_temp': None, 'gpu_temp': None, 'gpu_hotspot': None}

    try:
        from LibreHardwareMonitor.Hardware import SensorType

        result = {'cpu_temp': None, 'gpu_temp': None, 'gpu_hotspot': None}

        for hw in _computer.Hardware:
            hw.Update()
            for sensor in hw.Sensors:
                if sensor.SensorType == SensorType.Temperature and sensor.Value is not None:
                    val = float(sensor.Value)
                    name = sensor.Name.lower()
                    hw_name = hw.Name.lower()

                    # CPU 温度
                    if 'cpu' in hw_name or 'ryzen' in hw_name or 'intel' in hw_name:
                        if 'tdie' in name or 'tctl' in name or 'package' in name:
                            if val > 0:  # 0°C 通常是无效值
                                result['cpu_temp'] = val
                        elif result['cpu_temp'] is None and val > 0:
                            result['cpu_temp'] = val

                    # GPU 温度
                    if 'nvidia' in hw_name or 'gpu' in hw_name:
                        if 'hot spot' in name or 'hotspot' in name:
                            result['gpu_hotspot'] = val
                        elif 'core' in name or result['gpu_temp'] is None:
                            result['gpu_temp'] = val

            # 检查子硬件
            for sub in hw.SubHardware:
                sub.Update()
                for sensor in sub.Sensors:
                    if sensor.SensorType == SensorType.Temperature and sensor.Value is not None:
                        val = float(sensor.Value)
                        name = sensor.Name.lower()
                        if ('tdie' in name or 'tctl' in name or 'package' in name) and val > 0:
                            result['cpu_temp'] = val

        return result
    except Exception:
        return {'cpu_temp': None, 'gpu_temp': None, 'gpu_hotspot': None}


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    temps = read_temperatures()
    print(f"CPU Temp:    {temps['cpu_temp']} C" if temps['cpu_temp'] else "CPU Temp:    N/A (needs admin)")
    print(f"GPU Temp:    {temps['gpu_temp']:.1f} C" if temps['gpu_temp'] else "GPU Temp:    N/A")
    print(f"GPU HotSpot: {temps['gpu_hotspot']:.1f} C" if temps['gpu_hotspot'] else "GPU HotSpot: N/A")
