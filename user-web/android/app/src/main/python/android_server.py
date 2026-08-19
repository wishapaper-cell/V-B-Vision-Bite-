"""Start the health Flask application inside the Android process."""

import os


def start(database_path, resource_dir, upload_dir):
    os.environ["HEALTH_DB_PATH"] = database_path
    os.environ["HEALTH_RESOURCE_DIR"] = resource_dir
    os.environ["HEALTH_UPLOAD_DIR"] = upload_dir

    from app import app

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
