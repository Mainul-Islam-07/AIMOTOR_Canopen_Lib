"""Unit conversions for the AIMOTOR drive.

CiA402 on this drive counts in pulses, not rpm:
    speed         0x60FF / 0x606C   Pul/s
    acceleration  0x6083 / 0x6084   Pul/s^2
    position      0x607A / 0x6064   Pul
    torque        0x6071 / 0x6077   0.1 % of rated torque (1000 = rated)
    bus voltage   H0B_26            0.1 V
    phase current H0B_24            0.01 A

Pulses per revolution is the electronic gear setting H05-07 / H05-09,
factory default 1000. It lives in the JSON config, not in this file.
"""


class Units():
    def __init__(self, pulses_per_rev: int = 1000, gear_ratio: float = 1.0,
                 rated_torque_nm: float = 0.0, rated_current_a: float = 0.0):
        self.pulses_per_rev = int(pulses_per_rev) or 1000
        self.gear_ratio = float(gear_ratio) or 1.0
        self.rated_torque_nm = float(rated_torque_nm)
        self.rated_current_a = float(rated_current_a)

    # ------------------------------------------------------------- velocity

    def rpm_to_pulps(self, rpm: float) -> int:
        """100 rpm at 1000 pulses/rev -> 1667 Pul/s."""
        return int(round(float(rpm) / 60.0 * self.pulses_per_rev))

    def pulps_to_rpm(self, pulps: int) -> float:
        return float(pulps) * 60.0 / self.pulses_per_rev

    def rpm_s_to_pulps2(self, rpm_per_s: float) -> int:
        """Acceleration in rpm/s -> Pul/s^2."""
        return int(round(float(rpm_per_s) / 60.0 * self.pulses_per_rev))

    def pulps2_to_rpm_s(self, pulps2: int) -> float:
        return float(pulps2) * 60.0 / self.pulses_per_rev

    # ------------------------------------------------------------- position

    def pul_to_rev(self, pul: int) -> float:
        return float(pul) / self.pulses_per_rev

    def pul_to_deg(self, pul: int) -> float:
        return float(pul) / self.pulses_per_rev * 360.0

    def rev_to_pul(self, rev: float) -> int:
        return int(round(float(rev) * self.pulses_per_rev))

    def deg_to_pul(self, deg: float) -> int:
        return int(round(float(deg) / 360.0 * self.pulses_per_rev))

    def output_rev(self, pul: int) -> float:
        """Revolutions at the gearbox output shaft."""
        return self.pul_to_rev(pul) / self.gear_ratio

    # --------------------------------------------------------------- torque

    def permille_to_percent(self, raw: int) -> float:
        """Drive reports 0.1 % units: 1000 = 100 % of rated torque."""
        return float(raw) / 10.0

    def percent_to_permille(self, percent: float) -> int:
        return int(round(float(percent) * 10.0))

    def permille_to_nm(self, raw: int) -> float:
        """Needs rated_torque_nm in the config; returns 0.0 when unknown."""
        if not self.rated_torque_nm:
            return 0.0
        return float(raw) / 1000.0 * self.rated_torque_nm

    def nm_to_permille(self, nm: float) -> int:
        if not self.rated_torque_nm:
            return 0
        return int(round(float(nm) / self.rated_torque_nm * 1000.0))

    # ------------------------------------------------------ power monitoring

    def raw_to_volts(self, raw: int) -> float:
        """H0B_26 bus voltage, 0.1 V units."""
        return float(raw) / 10.0

    def raw_to_amps(self, raw: int) -> float:
        """H0B_24 phase current RMS, 0.01 A units."""
        return float(raw) / 100.0
