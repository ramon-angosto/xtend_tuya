from __future__ import annotations

import json

from typing import Any, Optional
from .ha_tuya_integration.tuya_integration_imports import (
    TuyaDPCodeIntegerWrapper,
    TuyaCustomerDevice,
    tuya_type_information_should_log_warning,
)
from .const import (
    LOGGER,
)


class XTDPCodeIntegerNoMinMaxCheckWrapper(TuyaDPCodeIntegerWrapper):
    """Simple wrapper for IntegerTypeInformation values."""

    def read_device_status(self, device: TuyaCustomerDevice) -> float | None:
        """Read and process raw value against this type information."""
        if (raw_value := device.status.get(self.dpcode)) is None:
            return None
        # Validate input against defined range
        if not isinstance(raw_value, int):
            if tuya_type_information_should_log_warning(
                device.id, f"integer_out_range|{self.dpcode}|{raw_value}"
            ):
                LOGGER.warning(
                    "Found invalid integer value `%s` for datapoint `%s` in product "
                    "id `%s`, expected integer value between %s and %s; please report "
                    "this defect to Tuya support",
                    raw_value,
                    self.dpcode,
                    device.product_id,
                    self.type_information.min,
                    self.type_information.max,
                )

            return None
        return self.type_information.scale_value(raw_value)

    def _convert_value_to_raw_value(
        self, device: TuyaCustomerDevice, value: float
    ) -> int:
        """Convert a Home Assistant value back to a raw device value."""
        return round(value * (10**self.type_information.scale))

class XTDPCodeBitmapLabelsWrapper(TuyaDPCodeTypeInformationWrapper[TuyaIntegerTypeInformation]):
    """Expose a BITMAP dpcode (bitmask) as a single sensor with decoded labels.

    Example output:
      - "00" (or "0") => no faults
      - "E01,E03"     => bits set correspond to those labels

    This is useful when you prefer ONE entity instead of multiple binary entities.
    """

    _DPTYPE = TuyaIntegerTypeInformation

    def __init__(
        self,
        dpcode: str,
        type_information: TuyaIntegerTypeInformation,
        labels: Optional[list[str]] = None,
    ) -> None:
        """Init bitmap wrapper."""
        super().__init__(dpcode, type_information)
        self._labels: list[str] = labels or []
        # This wrapper is read-only and returns a decoded string, so unit is empty.
        self.native_unit = ""

    @classmethod
    def find_dpcode(cls, device: TuyaCustomerDevice, dpcode: str, **kwargs: Any):
        """Find a BITMAP dpcode and build a wrapper that returns decoded labels.

        Restriction: only handle dpcode == "fault" to avoid wrapping unrelated bitmaps.
        """
        if str(dpcode) != "fault":
            return None

        status_range = getattr(device, "status_range", None) or {}
        if not isinstance(status_range, dict):
            return None

        sr = status_range.get(dpcode)
        if sr is None:
            return None

        # Only proceed if the dp really is a BITMAP
        if getattr(sr, "type", None) != TuyaDPType.BITMAP:
            return None

        # Parse valueDesc / values to extract labels
        values_raw = getattr(sr, "values", "{}") or "{}"
        values_dict: dict[str, Any] = {}
        if isinstance(values_raw, dict):
            values_dict = values_raw
        elif isinstance(values_raw, str):
            try:
                parsed = json.loads(values_raw) if values_raw else {}
                if isinstance(parsed, dict):
                    values_dict = parsed
            except Exception:
                values_dict = {}

        labels: list[str] = []
        label_value = values_dict.get("label", [])
        if isinstance(label_value, list):
            labels = [str(x) for x in label_value]

        # Build a minimal IntegerTypeInformation for HA's wrapper interface.
        # Some HA versions require keyword-only 'type_data'.
        max_int = 2**31 - 1

        type_data: dict[str, Any] = {
            "min": 0,
            "max": max_int,
            "scale": 0,
            "step": 1,
            "unit": "",
        }
        # Keep any extra metadata Tuya provided (like "label")
        for k, v in values_dict.items():
            if k not in type_data:
                type_data[k] = v

        try:
            type_info = TuyaIntegerTypeInformation(
                dpcode=dpcode,
                min=0,
                max=max_int,
                scale=0,
                step=1,
                unit="",
                type_data=type_data,
            )
        except TypeError:
            # Backward compatibility with older HA versions that did not require type_data
            type_info = TuyaIntegerTypeInformation(
                dpcode=dpcode,
                min=0,
                max=max_int,
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

        try:
            value_int = int(raw_value)
        except Exception:
            # If firmware sends something unexpected, show raw
            return str(raw_value)

        if value_int == 0:
            # Prefer "00" if Tuya provides it as the "OK" label
            return "00" if "00" in self._labels else "0"

        active: list[str] = []
        labels_len = len(self._labels)

        bit_index = 0
        tmp = value_int
        while tmp:
            if tmp & 1:
                if bit_index < labels_len:
                    label = self._labels[bit_index]
                    # Skip the "no fault" placeholder if it exists
                    if label not in ("00", "0"):
                        active.append(label)
                else:
                    active.append(f"bit{bit_index}")
            tmp >>= 1
            bit_index += 1

        if not active:
            return "00" if "00" in self._labels else "0"

        return ",".join(active)
        # new changes 
        # new_value = self.type_information.scale_value_back(value)
        # return new_value
