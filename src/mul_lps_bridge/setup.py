from setuptools import setup
from glob import glob
setup(name='mul_lps_bridge', version='0.1.0', packages=['mul_lps_bridge'],
 data_files=[('share/ament_index/resource_index/packages',['resource/mul_lps_bridge']),
 ('share/mul_lps_bridge',['package.xml']),('share/mul_lps_bridge/launch',glob('launch/*.py')),
 ('share/mul_lps_bridge/config',glob('config/*.yaml'))],
 install_requires=['setuptools'], zip_safe=True,
 maintainer='MUL maintainers', maintainer_email='80880227+Yacine-Derder@users.noreply.github.com',
 description='Read-only MUL bridge', license='Apache-2.0',
 entry_points={'console_scripts':['bridge = mul_lps_bridge.node:main']})
