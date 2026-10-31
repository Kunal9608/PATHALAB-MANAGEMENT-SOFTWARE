from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Any
import uuid


class TestParameterBase(BaseModel):
    parameter_name: str = Field(..., max_length=120)
    unit: Optional[str] = Field(None, max_length=20)
    input_type: str = Field("numeric", pattern="^(numeric|text|dropdown|select|multiline|formula)$")
    dropdown_options: Optional[List[str]] = None
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    reference_text: Optional[str] = Field(None, max_length=200)
    applicable_gender: str = Field("all", pattern="^(all|male|female)$")
    display_order: int = Field(1, ge=1, le=1000)

    @model_validator(mode="before")
    @classmethod
    def normalize_parameter_payload(cls, data: Any):
        if isinstance(data, dict):
            # Normalize gender / applicable_gender
            g = data.get("applicable_gender") or data.get("gender")
            if g:
                g_str = str(g).lower().strip()
                if g_str in ("all", "both", "any"):
                    data["applicable_gender"] = "all"
                elif g_str in ("male", "female"):
                    data["applicable_gender"] = g_str
                else:
                    data["applicable_gender"] = "all"
            else:
                data["applicable_gender"] = "all"

            # Normalize input_type
            itype = str(data.get("input_type", "numeric")).lower().strip()
            if itype in ("select", "dropdown", "options"):
                data["input_type"] = "dropdown"
            elif itype in ("multiline", "textarea", "narrative"):
                data["input_type"] = "multiline"
            elif itype in ("text", "string"):
                data["input_type"] = "text"
            else:
                data["input_type"] = "numeric"

            # Extract dropdown_options if input_type is dropdown
            if data["input_type"] == "dropdown" and not data.get("dropdown_options"):
                ref = data.get("reference_text")
                if ref and ("," in ref or "/" in ref):
                    delim = "," if "," in ref else "/"
                    data["dropdown_options"] = [opt.strip() for opt in ref.split(delim) if opt.strip()]

            # Extract numeric bounds if numeric input
            if data["input_type"] == "numeric" and (data.get("reference_low") is None and data.get("reference_high") is None):
                ref = data.get("reference_text")
                if ref:
                    import re
                    clean_ref = str(ref).replace(",", "").strip()
                    range_match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(?:-|to)\s*([0-9]+(?:\.[0-9]+)?)', clean_ref)
                    if range_match:
                        try:
                            data["reference_low"] = float(range_match.group(1))
                            data["reference_high"] = float(range_match.group(2))
                        except Exception:
                            pass
                    else:
                        lt_match = re.search(r'<\s*([0-9]+(?:\.[0-9]+)?)', clean_ref)
                        if lt_match:
                            try:
                                data["reference_high"] = float(lt_match.group(1))
                            except Exception:
                                pass
                        gt_match = re.search(r'>\s*([0-9]+(?:\.[0-9]+)?)', clean_ref)
                        if gt_match:
                            try:
                                data["reference_low"] = float(gt_match.group(1))
                            except Exception:
                                pass

        return data


class TestParameterCreate(TestParameterBase):
    pass


class TestParameterUpdate(BaseModel):
    parameter_name: Optional[str] = Field(None, max_length=120)
    unit: Optional[str] = Field(None, max_length=20)
    input_type: Optional[str] = Field(None, pattern="^(numeric|text|dropdown|select|multiline|formula)$")
    dropdown_options: Optional[List[str]] = None
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    reference_text: Optional[str] = Field(None, max_length=200)
    applicable_gender: Optional[str] = Field(None, pattern="^(all|male|female)$")
    display_order: Optional[int] = Field(None, ge=1, le=1000)


class TestParameterBulkSave(BaseModel):
    parameters: List[TestParameterCreate]


class TestParameterResponse(TestParameterBase):
    id: uuid.UUID
    test_id: uuid.UUID

    class Config:
        from_attributes = True
