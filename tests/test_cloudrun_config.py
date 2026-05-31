import pathlib
import re
import unittest


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]


class CloudRunProxyConfigTests(unittest.TestCase):
    def test_direct_page_redirects_stay_cloud_run_safe(self):
        config = (ROOT_DIR / "cloudrun-nginx.conf").read_text(encoding="utf-8")

        self.assertRegex(
            config,
            re.compile(
                r"location\s+~\s+\^/\(PyLOAD_V3\\\.0\|PyRUSH_V3\\\.0"
                r".*?return\s+302\s+/\?__loadpap_page=\$1;",
                re.S,
            ),
        )
        self.assertIn("absolute_redirect off;", config)
        self.assertIn("port_in_redirect off;", config)

    def test_nested_streamlit_routes_rewrite_all_stcore_runtime_paths(self):
        config = (ROOT_DIR / "cloudrun-nginx.conf").read_text(encoding="utf-8")

        self.assertRegex(
            config,
            re.compile(r"_stcore/\(health\|host-config\|stream\)", re.S),
        )

    def test_streamlit_startup_accepts_cloud_run_proxy_origin(self):
        script = (ROOT_DIR / "cloudrun-start.sh").read_text(encoding="utf-8")

        self.assertIn("--server.enableCORS=false", script)
        self.assertIn("--server.enableXsrfProtection=false", script)

    def test_streamlit_root_location_inherits_websocket_proxy_headers(self):
        config = (ROOT_DIR / "cloudrun-nginx.conf").read_text(encoding="utf-8")
        location_root = re.search(r"location / \{(?P<body>.*?)\n        \}", config, re.S)

        self.assertIsNotNone(location_root)
        self.assertIn('proxy_set_header Accept-Encoding "";', config)
        self.assertNotIn("proxy_set_header", location_root.group("body"))


if __name__ == "__main__":
    unittest.main()
