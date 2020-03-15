# Copyright 2019 Atalaya Tech, Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

# http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import, division, print_function

import os
import shutil
import logging
import multiprocessing

from gunicorn.app.base import Application

from bentoml import config
from bentoml.marshal import MarshalService
from bentoml.utils.usage_stats import track_server


marshal_logger = logging.getLogger("bentoml.marshal")


class GunicornMarshalServer(Application):  # pylint: disable=abstract-method
    def __init__(
        self,
        target_host,
        target_port,
        bundle_path,
        port=None,
        num_of_workers=1,
        timeout=None,
    ):
        self.bento_service_bundle_path = bundle_path

        self.target_port = target_port
        self.target_host = target_host
        self.port = port or config("apiserver").getint("default_port")
        timeout = timeout or config("apiserver").getint("default_timeout")
        self.options = {
            "bind": "%s:%s" % ("0.0.0.0", self.port),
            "timeout": timeout,
            "loglevel": config("logging").get("LOGGING_LEVEL").upper(),
            "worker_class": "aiohttp.worker.GunicornWebWorker",
        }
        if num_of_workers:
            self.options['workers'] = num_of_workers

        super(GunicornMarshalServer, self).__init__()

    def load_config(self):
        self.load_config_from_file("python:bentoml.server.gunicorn_config")

        # override config with self.options
        gunicorn_config = dict(
            [
                (key, value)
                for key, value in self.options.items()
                if key in self.cfg.settings and value is not None
            ]
        )
        for key, value in gunicorn_config.items():
            self.cfg.set(key.lower(), value)

    def setup_prometheus_multiproc_dir(self):
        """
        Set up prometheus_multiproc_dir for prometheus to work in multiprocess mode,
        which is required when working with Gunicorn server

        Warning: for this to work, prometheus_client library must be imported after
        this function is called. It relies on the os.environ['prometheus_multiproc_dir']
        to properly setup for multiprocess mode
        """

        prometheus_multiproc_dir = config('instrument').get('prometheus_multiproc_dir')
        marshal_logger.debug(
            "Setting up prometheus_multiproc_dir: %s", prometheus_multiproc_dir
        )
        if os.path.isdir(prometheus_multiproc_dir):
            shutil.rmtree(prometheus_multiproc_dir)
        os.mkdir(prometheus_multiproc_dir)
        os.environ['prometheus_multiproc_dir'] = prometheus_multiproc_dir

    def load(self):
        server = MarshalService(
            self.bento_service_bundle_path, self.target_host, self.target_port,
        )
        return server.make_app()

    def run(self):
        track_server('gunicorn-microbatch', {"number_of_workers": self.cfg.workers})
        self.setup_prometheus_multiproc_dir()
        super(GunicornMarshalServer, self).run()

    def async_run(self):
        """
        Start an micro batch server.
        """
        marshal_proc = multiprocessing.Process(target=self.run, daemon=True,)
        marshal_proc.start()
        marshal_logger.info("Running micro batch service on :%d", self.port)
