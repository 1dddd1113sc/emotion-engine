import wmi, sys
sys.stdout.reconfigure(encoding='utf-8')
try:
    c = wmi.WMI(namespace=r'root\WMI')
    temps = c.MSAcpi_ThermalZoneTemperature()
    for t in temps:
        celsius = t.CurrentTemperature / 10.0 - 273.15
        print(f'{t.InstanceName}: {celsius:.1f}C')
except Exception as e:
    print(f'ERROR: {e}')
