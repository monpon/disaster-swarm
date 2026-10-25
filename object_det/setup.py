import os
from glob import glob
from setuptools import find_packages, setup

package_name = "object_det"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
        (os.path.join("share", package_name, "models"), ["model.pt"] if os.path.exists("model.pt") else []),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Disaster Swarm Team",
    maintainer_email="swarm@disaster-response.org",
    description="ROS 2 node running YOLO on 240p camera stream, broadcasting detected classes and bounding boxes",
    license="MIT",
    entry_points={
        "console_scripts": [
            "detector_node = object_det.detector_node:main",
            "mock_camera_node = object_det.mock_camera_node:main",
        ],
    },
)
