# common/data.py
import json
import streamlit as st
from typing import Dict, Any, Optional
from datetime import datetime

DEFAULT_DATA_PATH = "data_v2.json"

def load_data() -> Dict[str, Any]:
    """
    Load data from the default JSON file with UTF-8 encoding to prevent
    'charmap' decode errors on Windows systems.
    """
    if "data" not in st.session_state or st.session_state.data is None:
        try:
            # Explicitly setting encoding="utf-8" solves the 'charmap' error
            with open("data_v2.json", "r", encoding="utf-8") as f:
                st.session_state.data = json.load(f)
                st.session_state.uploaded_file_name = "data_v2.json"
        except FileNotFoundError:
            st.session_state.data = None
        except Exception as e:
            # Re-raise or handle as needed
            st.error(f"Error loading data: {e}")
            st.session_state.data = None
    return st.session_state.data

def save_data(data: Dict[str, Any]):
    """
    Save data to the default JSON file. 
    Uses ensure_ascii=False to keep emojis and special characters readable.
    """
    try:
        with open("data_v2.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        st.session_state.last_save_time = datetime.now()
    except Exception as e:
        st.error(f"Error saving data: {e}")

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
            # Use UTF-8 encoding here as well
            with open(auto_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                st.session_state.data = data
                st.session_state.uploaded_file_name = auto_path
                # Optional toast notification
                st.toast(
                    f"✅ Auto-loaded {len(data.get('resorts', []))} resorts from {auto_path}",
                    icon="✅",
                )
        except FileNotFoundError:
            # No default file, just start empty
            pass
        except Exception as e:
            # Catching the encoding error here and displaying it
            st.toast(f"⚠️ Auto-load error: {e}", icon="⚠️")


def render_data_file_uploader(
    label: str,
    session_key: str,
    uploaded_name_key: str,
    uploader_key: str,
    help_text: str = "",
    require_schema: bool = True,
) -> None:
    """
    Renders a Streamlit file uploader. Manual uploads usually work because 
    Streamlit handles the byte-to-string conversion internally.
    """
    uploaded_file = st.file_uploader(
        label,
        type="json",
        key=uploader_key,
        help=help_text,
    )

    if not uploaded_file:
        return

    try:
        # st.file_uploader returns a file-like object that json.load handles well
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
