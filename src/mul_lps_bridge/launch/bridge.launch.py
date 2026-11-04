from pathlib import Path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def configure(context):
    def value(name):
        return LaunchConfiguration(name).perform(context)
    alr = int(value('alr_id'))
    if alr not in (132,133,134,135):
        raise ValueError('alr_id must be 132..135')
    config = value('config') or str(Path(get_package_share_directory('mul_lps_bridge'))/'config'/f'alr_{alr}.yaml')
    overrides = {'alr_id':alr}
    for key in ('serial_device','raw_log'):
        if value(key):
            overrides[key] = value(key)
    if value('baud_rate'):
        overrides['baud_rate'] = int(value('baud_rate'))
    namespace = value('namespace') or f'/uwb/alr_{alr}'
    return [Node(package='mul_lps_bridge',executable='bridge',namespace=namespace,
                 parameters=[config,overrides],output='screen')]


def generate_launch_description():
    defaults = dict(alr_id='132',config='',serial_device='',baud_rate='',namespace='',raw_log='')
    return LaunchDescription([DeclareLaunchArgument(k,default_value=v) for k,v in defaults.items()]+[OpaqueFunction(function=configure)])
