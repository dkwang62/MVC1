# common/data.py
import json
import streamlit as st
from typing import Dict, Any, Optional
from datetime import datetime

DEFAULT_DATA_PATH = "data_v2.json"

def load_data() -> Dict[str, Any]:
    if "data" not in st.session_state or st.session_state.data is None:
        try:
            with open("data_v2.json", "r") as f:
                st.session_state.data = json.load(f)
                st.session_state.uploaded_file_name = "data_v2.json"
        except FileNotFoundError:
            st.session_state.data = None
    return st.session_state.data

def save_data(data: Dict[str, Any]):
    with open("data_v2.json", "w") as f:
        json.dump(data, f, indent=2)
    st.session_state.last_save_time = datetime.now()

def ensure_data_in_session(auto_path: str = DEFAULT_DATA_PATH) -> None:
    """
    Make sure st.session_state.data and st.session_state.uploaded_file_name exist
    and, if empty, try to auto-load from disk.
    """
    # Ensure keys exist
    if "data" not in st.session_state:
        st.session_state.data = None
    if "uploaded_file_name" not in st.session_state:
        st.session_state.uploaded_file_name = None

    # If nothing loaded yet, try auto-load from disk
    if st.session_state.data is None:
        try:
            with open(auto_path, "r") as f:
                data = json.load(f)
            # Basic schema sanity check
            if "schema_version" in data and "resorts" in data:
                st.session_state.data = data
                st.session_state.uploaded_file_name = auto_path
                # Optional toast, safe even if it fires only once
                st.toast(
                    f"✅ Auto-loaded {len(data.get('resorts', []))} resorts from {auto_path}",
                    icon="✅",
                )
        except FileNotFoundError:
            # No default file, just start empty
            pass
        except Exception as e:
            # Silent failure; individual pages can show their own messaging
            st.toast(f"⚠️ Auto-load error: {e}", icon="⚠️")


def render_data_file_uploader(
    label: str,
    session_key: str,
    uploaded_name_key: str,
    uploader_key: str,
    help_text: str = "",
    require_schema: bool = True,
) -> None:
    import json
    import streamlit as st

    uploaded_file = st.file_uploader(
        label,
        type="json",
        key=uploader_key,
        help=help_text,
    )

    if not uploaded_file:
        return

    try:
        data = json.load(uploaded_file)
    except Exception as e:
        st.error(f"❌ Error loading JSON: {e}")
        return

    if require_schema:
        if not isinstance(data, dict) or "schema_version" not in data or "resorts" not in data:
            st.error("❌ Uploaded file does not match expected MVC schema.")
            return

    st.session_state[session_key] = data
    st.session_state[uploaded_name_key] = uploaded_file.name
    st.success(f"✅ Loaded {uploaded_file.name}")
    st.rerun()
