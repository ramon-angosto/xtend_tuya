from __future__ import annotations

import json

from typing import Any, Optional
from .ha_tuya_integration.tuya_integration_imports import (
    TuyaDPCodeTypeInformationWrapper,
    TuyaCustomerDevice,
    TuyaIntegerTypeInformation,
    TuyaDPType,
)
from .type_information import XTIntegerNoMinMaxCheckTypeInformation

class XTDPCodeIntegerNoMinMaxCheckWrapper(TuyaDPCodeTypeInformationWrapper[XTIntegerNoMinMaxCheckTypeInformation]):
    """Simple wrapper for IntegerTypeInformation values."""

    _DPTYPE = XTIntegerNoMinMaxCheckTypeInformation

    def __init__(self, dpcode: str, type_information: XTIntegerNoMinMaxCheckTypeInformation) -> None:
        """Init DPCodeIntegerWrapper."""
        super().__init__(dpcode, type_information)
        self.native_unit = type_information.unit
        self.min_value = self.type_information.scale_value(type_information.min)
        self.max_value = self.type_information.scale_value(type_information.max)
        self.value_step = self.type_information.scale_value(type_information.step)

    def _convert_value_to_raw_value(self, device: TuyaCustomerDevice, value: Any) -> Any:
        """Convert a Home Assistant value back to a raw device value."""
        return round(value * (10**self.type_information.scale))

class XTDPCodeBitmapLabelsWrapper(TuyaDPCodeTypeInformationWrapper[TuyaIntegerTypeInformation]):
    """Bitmap DP wrapper that exposes a single sensor with decoded labels.

    Tuya uses BITMAP dptype for bit masks like:
      - 0b000 -> no fault
      - 0b101 -> bits 0 and 2 active

    The official Tuya HA wrapper set tends to focus on exposing *one binary sensor per bit*.
    For devices where users prefer a *single entity*, this wrapper converts the bitmap
    to a comma-separated string of active labels (e.g. "E01,E03"), or "00" when empty.

    Notes:
      - Labels are extracted from the dp "values" JSON (valueDesc) when available.
      - When the device reports bits beyond the known label list, we add "bitN".
    """

    _DPTYPE = TuyaIntegerTypeInformation

    def __init__(
        self,
        dpcode: str,
        type_information: TuyaIntegerTypeInformation,
        labels: Optional[list[str]] = None,
    ) -> None:
        """Init XT bitmap wrapper."""
        super().__init__(dpcode, type_information)
        self._labels: list[str] = labels or []

    @classmethod
    def find_dpcode(cls, device: TuyaCustomerDevice, dpcode: str, **kwargs: Any):
        """Find a bitmap dpcode and wrap it as an integer + decoded label sensor."""
        status_range = getattr(device, "status_range", {}) or {}
        if dpcode not in status_range:
            return None

        sr = status_range[dpcode]
        if getattr(sr, "type", None) != TuyaDPType.BITMAP:
            return None

        # Try to read labels from the 'values' JSON (valueDesc)
        labels: list[str] = []
        values_raw = getattr(sr, "values", "{}") or "{}"
        try:
            values_dict = json.loads(values_raw) if isinstance(values_raw, str) else {}
            labels_value = values_dict.get("label", [])
            if isinstance(labels_value, list):
                labels = [str(x) for x in labels_value]
        except Exception:
            labels = []

        # Map bitmap to a "plain integer" type info (no scaling, huge max)
        type_info = TuyaIntegerTypeInformation(
            dpcode=dpcode,
            min=0,
            max=2**31 - 1,
            scale=0,
            step=1,
            unit="",
        )
        return cls(dpcode, type_info, labels=labels)

    def read_device_status(self, device: TuyaCustomerDevice):  # type: ignore[override]
        """Read device status and return a decoded label string."""
        raw_value = getattr(device, "status", {}).get(self.dpcode)
        if raw_value is None:
            return None

        # Some firmwares send bitmap as stringified int
        try:
            value_int = int(raw_value)
        except Exception:
            return None

        if value_int == 0:
            # If the device provides an explicit "no fault" label, use it.
            if "00" in self._labels:
                return "00"
            return "0"

        active: list[str] = []
        labels_len = len(self._labels)

        bit_index = 0
        temp = value_int
        while temp:
            if temp & 1:
                if bit_index < labels_len:
                    label = self._labels[bit_index]
                    if label != "00":
                        active.append(label)
                else:
                    active.append(f"bit{bit_index}")
            temp >>= 1
            bit_index += 1

        if not active:
            return "00" if "00" in self._labels else "0"

        # Stable ordering: lowest bit first
        return ",".join(active)
