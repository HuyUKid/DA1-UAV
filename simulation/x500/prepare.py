#!/usr/bin/env python3
"""Port PX4's actual x500 model to Classic, retaining the Classic MAVLink HIL bridge."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as E
from paths import default_px4

HERE = Path(__file__).resolve().parent


def make_world_self_contained(world):
    """Keep the test world independent of the remote Gazebo model database."""
    node = world.getroot().find('world')
    for include in list(node.findall('include')):
        uri = include.findtext('uri')
        if uri in ('model://sun', 'model://ground_plane', 'model://asphalt_plane'):
            node.remove(include)
        elif uri == 'model://iris_hitl':
            set_text(include, 'uri', 'model://x500_hitl')
            set_text(include, 'pose', '0 0 0.25 0 0 0')
    if node.find("light[@name='sun']") is None:
        node.append(E.fromstring('''<light name="sun" type="directional">
          <cast_shadows>true</cast_shadows><pose>0 0 10 0 0 0</pose>
          <diffuse>0.8 0.8 0.8 1</diffuse><specular>0.2 0.2 0.2 1</specular>
          <attenuation><range>1000</range><constant>0.9</constant>
          <linear>0.01</linear><quadratic>0.001</quadratic></attenuation>
          <direction>-0.5 0.1 -0.9</direction></light>'''))
    if node.find("model[@name='ground_plane']") is None:
        node.append(E.fromstring('''<model name="ground_plane"><static>true</static>
          <link name="ground"><collision name="collision"><geometry><plane>
          <normal>0 0 1</normal><size>100 100</size></plane></geometry>
          <surface><friction><ode><mu>1</mu><mu2>1</mu2></ode></friction></surface>
          </collision><visual name="visual"><geometry><plane><normal>0 0 1</normal>
          <size>100 100</size></plane></geometry><material>
          <ambient>0.4 0.4 0.4 1</ambient><diffuse>0.6 0.6 0.6 1</diffuse>
          </material></visual></link></model>'''))
    for tag in ('gravity', 'magnetic_field'):
        element = node.find(f'physics/{tag}')
        if element is not None:
            node.find('physics').remove(element)
            node.append(element)
    world.getroot().set('version', '1.6')


def set_text(node, tag, value):
    element = node.find(tag)
    if element is None:
        element = E.SubElement(node, tag)
    element.text = str(value)


def prepare(px4, serial, baud, output):
    gz_models = px4 / 'Tools/simulation/gz/models'
    classic = px4 / 'Tools/simulation/gazebo-classic/sitl_gazebo-classic'
    base_path = gz_models / 'x500_base/model.sdf'
    motor_path = gz_models / 'x500/model.sdf'
    bridge_path = classic / 'models/iris_hitl/iris_hitl.sdf'
    sources = [base_path, motor_path, bridge_path]
    for path in sources:
        if not path.is_file():
            raise ValueError(f'Missing PX4 source: {path}')
    base = E.parse(base_path).getroot().find('model')
    x500 = E.parse(motor_path).getroot().find('model')
    iris = E.parse(bridge_path).getroot().find('model')
    # Keep geometry, collisions, mass, inertia, motor positions and joints from x500.
    model = copy.deepcopy(base)
    model.set('name', 'x500_hitl')
    pose = model.find('pose')
    if pose is not None:
        model.remove(pose)  # Spawn height is supplied by the world, once.
    for link in model.findall('link'):
        for sensor in link.findall('sensor'):
            link.remove(sensor)  # GZ sensor systems replaced by Classic sensor plugins.
        for material in link.findall('.//material'):
            for pbr in material.findall('pbr'):
                material.remove(pbr)  # Classic renderer uses diffuse/ambient + mesh materials.
    # Classic IMU/GPS and HIL transport, without Iris body or propulsion dynamics.
    for name in ('/imu_link', '/imu_joint'):
        element = next(e for e in iris if e.get('name') == name)
        model.append(copy.deepcopy(element))
    for element in iris:
        if element.tag == 'model' or (element.tag == 'joint' and element.get('name') == 'gps0_joint'):
            model.append(copy.deepcopy(element))
        if element.tag == 'plugin' and element.get('filename') != 'libgazebo_motor_model.so':
            model.append(copy.deepcopy(element))
    # __default__ is a placeholder rather than a loadable material script.
    for material in model.findall('.//material'):
        script = material.find('script')
        if script is not None and script.findtext('uri') == '__default__':
            material.remove(script)
            set_text(material, 'ambient', '0.5 0.5 0.5 1')
            set_text(material, 'diffuse', '0.5 0.5 0.5 1')
    # Same x500 thrust/drag constants and spin directions, Classic plugin implementation.
    for index, motor in enumerate(x500.findall('plugin')):
        if 'motor-model' not in motor.get('filename', ''):
            continue
        plugin = copy.deepcopy(motor)
        plugin.set('name', f'x500_motor_{index}')
        plugin.set('filename', 'libgazebo_motor_model.so')
        E.SubElement(plugin, 'robotNamespace')
        set_text(plugin, 'commandSubTopic', '/gazebo/command/motor_speed')
        set_text(plugin, 'motorSpeedPubTopic', f'/motor_speed/{index}')
        for element in plugin.findall('motorType'):
            plugin.remove(element)
        model.append(plugin)
    # GZ uses per-sample standard deviation; Classic takes noise density.
    # Make the conversion explicit instead of inheriting unknown compiled defaults.
    imu_source = base.find("link[@name='base_link']/sensor[@type='imu']")
    rate = float(imu_source.findtext('update_rate'))
    gyro_std = max(float(e.text) for e in imu_source.findall('imu/angular_velocity/*/noise/stddev'))
    accel_std = max(float(e.text) for e in imu_source.findall('imu/linear_acceleration/*/noise/stddev'))
    imu = model.find("plugin[@filename='libgazebo_imu_plugin.so']")
    for key, value in {'gyroscopeNoiseDensity': gyro_std / math.sqrt(rate),
                       'accelerometerNoiseDensity': accel_std / math.sqrt(rate),
                       'gyroscopeRandomWalk': 0, 'accelerometerRandomWalk': 0,
                       'gyroscopeTurnOnBiasSigma': 0, 'accelerometerTurnOnBiasSigma': 0,
                       'gyroscopeBiasCorrelationTime': 1000, 'accelerometerBiasCorrelationTime': 300}.items():
        set_text(imu, key, value)
    gps = model.find("model[@name='gps0']/link/sensor/plugin")
    set_text(gps, 'update_rate', base.findtext("link[@name='base_link']/sensor[@type='navsat']/update_rate"))
    bridge = model.find("plugin[@name='mavlink_interface']")
    settings = {'serialEnabled': 1, 'serialDevice': serial, 'baudRate': baud,
                'hil_mode': 1, 'hil_state_level': 0, 'enable_lockstep': 0,
                'use_tcp': 0, 'send_odometry': 0, 'send_vision_estimation': 0,
                'qgc_addr': '127.0.0.1', 'sdk_addr': '127.0.0.1'}
    for key, value in settings.items():
        set_text(bridge, key, value)
    channels = bridge.find('control_channels')
    for channel in list(channels):
        index = int(channel.findtext('input_index'))
        if index >= 4:
            channels.remove(channel)
        else:
            # GZ x500 uses 150..1000 rad/s for armed normalized input 0..1.
            set_text(channel, 'input_scaling', 850)
            set_text(channel, 'zero_position_armed', 150)
            set_text(channel, 'zero_position_disarmed', 0)
    models = output / 'models'
    destination = models / 'x500_hitl'
    destination.mkdir(parents=True, exist_ok=True)
    # Original mesh URIs reference x500_base; copy its resources unchanged.
    shutil.copytree(gz_models / 'x500_base', models / 'x500_base', dirs_exist_ok=True)
    shutil.copy2(gz_models / 'x500/LICENSE', destination / 'LICENSE.x500')
    shutil.copy2(px4 / 'LICENSE', destination / 'LICENSE.PX4')
    sdf = E.Element('sdf', version='1.6')
    sdf.append(model)
    E.indent(sdf)
    E.ElementTree(sdf).write(destination / 'model.sdf', encoding='utf-8', xml_declaration=True)
    config = E.fromstring('<model><name>x500_hitl</name><version>1.0</version><sdf version="1.6">model.sdf</sdf><description>PX4 x500 port with Gazebo Classic MAVLink HITL bridge</description></model>')
    E.indent(config)
    E.ElementTree(config).write(destination / 'model.config', encoding='utf-8', xml_declaration=True)
    world = E.parse(classic / 'worlds/hitl_iris.world')
    node = world.getroot().find('world')
    node.set('name', 'x500_hitl_world')
    make_world_self_contained(world)
    E.indent(world)
    world.write(output / 'x500_hitl.world', encoding='utf-8', xml_declaration=True)
    def revision(path):
        return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    metadata = {'px4_path': str(px4), 'gz_models_revision': revision(gz_models),
                'classic_revision': revision(classic), 'serial_device': serial, 'baud': baud,
                'source_sha256': {str(p.relative_to(px4)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                'imu_noise_mapping': {'gyro_std_rad_s': gyro_std, 'accel_std_m_s2_isotropic_max': accel_std, 'rate_hz': rate, 'turn_on_bias': 0},
                'body_mass_kg': float(model.findtext('link[@name="base_link"]/inertial/mass')),
                'total_link_mass_kg': sum(float(e.text) for e in model.findall('.//inertial/mass')),
                'port_adjustments': ['Inline ground plane and sun; no remote world model dependencies',
                                     'Replace placeholder GPS material with explicit colours'],
                'limitations': ['Classic sensor models replace GZ sensors', 'PBR removed for Classic renderer',
                                'Model parameters represent upstream x500, not measured user airframe',
                                'Hardware flight not certified by model generation']}
    (output / 'provenance.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return output / 'x500_hitl.world'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--px4', type=Path, default=default_px4())
    parser.add_argument('--serial', default='/dev/serial/by-id/usb-Auterion_PX4_FMU_v6C.x_0-if00')
    parser.add_argument('--baud', type=int, default=921600)
    parser.add_argument('--output', type=Path, default=HERE / 'generated')
    args = parser.parse_args()
    if not args.serial.startswith('/dev/') or args.baud <= 0:
        parser.error('Expected /dev/... serial device and positive baud')
    print(prepare(args.px4.resolve(), args.serial, args.baud, args.output.resolve()))


if __name__ == '__main__':
    main()
