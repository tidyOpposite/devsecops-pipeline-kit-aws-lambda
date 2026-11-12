"""Stored ECR image integrity and registry redirect boundaries."""

import hashlib
import io
import json
import subprocess
import unittest
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from devsecops_cli import aws as aws_provider
from devsecops_cli.models import ConfigValidationError

ROOT_DIR = Path(__file__).resolve().parents[2]


class EcrImageVerificationTests(unittest.TestCase):
    registry = "210987654321.dkr.ecr.us-east-1.amazonaws.com"
    image_uri = registry + "/external/lambda:sha-abc123"
    layer_digest = "sha256:" + "f" * 64

    def test_validates_stored_manifest_and_platform_with_the_image_registry(self) -> None:
        cases = [
            (
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.oci.image.config.v1+json",
                "amd64",
                None,
            ),
            (
                "application/vnd.docker.distribution.manifest.v2+json",
                "application/vnd.docker.container.image.v1+json",
                "amd64",
                None,
            ),
            (
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.oci.image.config.v1+json",
                "arm64",
                "linux/amd64",
            ),
            (
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.oci.image.config.v1+json",
                "amd64",
                "Cannot pull",
            ),
            ("application/vnd.oci.image.index.v1+json", "", "amd64", "single-platform"),
        ]
        for media_type, config_type, architecture, error in cases:
            with self.subTest(media_type=media_type, architecture=architecture, error=error):
                blob = json.dumps({"os": "linux", "architecture": architecture}).encode()
                config_digest = "sha256:" + hashlib.sha256(blob).hexdigest()
                manifest = json.dumps(
                    {
                        "schemaVersion": 2,
                        "mediaType": media_type,
                        "config": {
                            "mediaType": config_type,
                            "digest": config_digest,
                            "size": len(blob),
                        },
                        "layers": [{"digest": self.layer_digest}],
                    }
                )
                digest = "sha256:" + hashlib.sha256(manifest.encode()).hexdigest()
                identity = {
                    "imageId": {"imageDigest": digest},
                    "registryId": "210987654321",
                    "repositoryName": "external/lambda",
                }
                responses = [
                    {"images": [identity]},
                    {"images": [{**identity, "imageManifest": manifest}]},
                    {
                        "layerDigest": self.layer_digest,
                        "downloadUrl": "https://s3.example.test/layer",
                    },
                    {"authorizationData": [{"authorizationToken": "ZmFrZQ=="}]},
                ]
                completed = subprocess.CompletedProcess([], 0, "", "")
                results = [(response, completed) for response in responses]
                if error == "Cannot pull":
                    results[2] = (
                        {},
                        subprocess.CompletedProcess([], 254, "", "AccessDeniedException"),
                    )
                with (
                    patch.object(aws_provider, "_read_ecr_config", return_value=blob) as read_blob,
                    patch.object(aws_provider, "_aws_json", side_effect=results) as aws,
                ):
                    args = (ROOT_DIR, self.image_uri, "us-east-1")
                    if error:
                        with self.assertRaisesRegex(ConfigValidationError, error):
                            aws_provider.verify_ecr_lambda_image(*args, aws_json_fn=aws)
                    else:
                        self.assertEqual(
                            aws_provider.verify_ecr_lambda_image(*args, aws_json_fn=aws),
                            self.registry + "/external/lambda@" + digest,
                        )
                    self.assertIn("imageTag=sha-abc123", aws.call_args_list[0].args[1])
                    self.assertIn("imageDigest=" + digest, aws.call_args_list[1].args[1])
                    for call in aws.call_args_list:
                        command = call.args[1]
                        if "--registry-id" in command:
                            self.assertEqual(
                                command[command.index("--registry-id") + 1], "210987654321"
                            )
                    if config_type and error != "Cannot pull":
                        read_blob.assert_called_once_with(
                            aws_provider.parse_ecr_image_uri(self.image_uri),
                            config_digest,
                            len(blob),
                            "ZmFrZQ==",
                        )
                    else:
                        read_blob.assert_not_called()

    def test_registry_blob_redirect_omits_authorization(self) -> None:
        requests = []
        target = "https://s3.example.test/blob"

        def respond(handler, request):
            requests.append(request)
            headers = Message()
            if len(requests) == 1:
                headers["Location"] = target
                response = urllib.response.addinfourl(
                    io.BytesIO(b""), headers, request.full_url, 307
                )
                response.msg = "Temporary Redirect"
                return response
            response = urllib.response.addinfourl(
                io.BytesIO(b"config"), headers, request.full_url, 200
            )
            response.msg = "OK"
            return response

        ref = aws_provider.parse_ecr_image_uri(self.image_uri)
        with patch.object(
            urllib.request.HTTPSHandler, "https_open", autospec=True, side_effect=respond
        ):
            self.assertEqual(
                aws_provider._read_ecr_config(ref, self.layer_digest, 6, "ZmFrZQ=="), b"config"
            )
        self.assertEqual(requests[0].get_header("Authorization"), "Basic ZmFrZQ==")
        self.assertEqual(requests[1].full_url, target)
        self.assertIsNone(requests[1].get_header("Authorization"))
