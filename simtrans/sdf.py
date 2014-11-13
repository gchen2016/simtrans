# -*- coding:utf-8 -*-

"""
Reader and writer for SDF format
"""

from logging import getLogger
logger = getLogger(__name__)

import os
import lxml.etree
import numpy
import warnings
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    from .thirdparty import transformations as tf
import jinja2
from . import model
from . import collada
from . import stl
from . import utils

class SDFReader(object):
    '''
    SDF reader class
    '''
    def read(self, fname):
        '''
        Read SDF model data given the model file

        >>> r = SDFReader()
        >>> m = r.read('model://pr2/model.sdf')
        '''
        bm = model.BodyModel()
        d = lxml.etree.parse(open(utils.resolveFile(fname)))
        dm = d.find('model')
        bm.name = dm.attrib['name']

        for l in dm.findall('link'):
            # general information
            lm = model.LinkModel()
            lm.name = l.attrib['name']
            pose = l.find('pose')
            if pose is not None:
                self.readPose(lm, pose)
            # phisical property
            inertial = l.find('inertial')
            if inertial is not None:
                lm.mass = float(inertial.find('mass').text)
                pose = inertial.find('pose')
                if pose is not None:
                    lm.centerofmass = [float(v) for v in pose.text.split(' ')][0:3]
                lm.inertia = self.readInertia(inertial.find('inertia'))
            # visual property
            lm.visuals = []
            for v in l.findall('visual'):
                lm.visuals.append(self.readShape(v))
            # contact property
            #collision = l.find('collision')
            #if collision is not None:
            #    lm.collision = self.readShape(collision)
            bm.links.append(lm)

        for j in dm.findall('joint'):
            jm = model.JointModel()
            # general property
            jm.name = j.attrib['name']
            jm.jointType = self.readJointType(j.attrib['type'])
            pose = j.find('pose')
            if pose is not None:
                self.readPose(jm, pose)
            axis = j.find('axis')
            if axis is not None:
                jm.axis = [float(v) for v in axis.find('xyz').text.split(' ')]
                dynamics = axis.find('dynamics')
                if dynamics is not None:
                    jm.damping = dynamics.find('damping').text
                    jm.friction = dynamics.find('friction').text
                limit = axis.find('limit')
                if limit is not None:
                    jm.limit = [limit.find('upper').text, limit.find('lower').text]
            jm.parent = j.find('parent').text
            jm.child = j.find('child').text
            # phisical property
            bm.joints.append(jm)

        return bm

    def readPose(self, m, doc):
        pose = numpy.array([float(v) for v in doc.text.split(' ')])
        m.trans = pose[0:3]
        m.rot = tf.quaternion_from_euler(pose[3], pose[4], pose[5])

    def readJointType(self, d):
        if d == "fixed":
            return model.JointModel.J_FIXED
        elif d == "revolute":
            return model.JointModel.J_REVOLUTE
        elif d == 'prismatic':
            return model.JointModel.J_PRISMATIC
        elif d == 'screw':
            return model.JointModel.J_SCREW
        raise Exception('unsupported joint type: %s' % d)

    def readInertia(self, d):
        inertia = numpy.zeros((3, 3))
        inertia[0, 0] = float(d.find('ixx').text)
        inertia[0, 1] = inertia[1, 0] = float(d.find('ixy').text)
        inertia[0, 2] = inertia[2, 0] = float(d.find('ixz').text)
        inertia[1, 1] = float(d.find('iyy').text)
        inertia[1, 2] = inertia[2, 1] = float(d.find('iyz').text)
        inertia[2, 2] = float(d.find('izz').text)
        return inertia

    def readShape(self, d):
        m = model.ShapeModel()
        m.name = d.attrib['name']
        pose = d.find('pose')
        if pose is not None:
            self.readPose(m, pose)
        for g in d.find('geometry').getchildren():
            if g.tag == 'mesh':
                m.shapeType = model.ShapeModel.SP_MESH
                # print "reading mesh " + mesh.attrib['filename']
                filename = utils.resolveFile(g.find('uri').text)
                fileext = os.path.splitext(filename)[1].lower()
                if fileext == '.dae':
                    reader = collada.ColladaReader()
                elif fileext == '.stl':
                    reader = stl.STLReader()
                else:
                    raise Exception('unsupported mesh format: %s' % fileext)
                m.data = reader.read(filename)
            elif g.tag == 'box':
                m.shapeType = model.ShapeModel.SP_BOX
                boxsize = [float(v) for v in g.find('size').text.split(' ')]
                m.data = model.BoxData()
                m.data.x = boxsize[0]
                m.data.y = boxsize[1]
                m.data.z = boxsize[2]
            elif g.tag == 'cylinder':
                m.shapeType = model.ShapeModel.SP_CYLINDER
                m.data = model.CylinderData()
                m.data.radius = float(g.find('radius').text)
                m.data.height = float(g.find('length').text)
            elif g.tag == 'sphere':
                m.shapeType = model.ShapeModel.SP_SPHERE
                m.data = model.SphereData()
                m.data.radius = float(g.find('radius').text)
            else:
                raise Exception('unsupported shape type: %s' % g.tag)
        return m


class SDFWriter(object):
    '''
    SDF writer class
    '''
    def write(self, m, f):
        '''
        Write simulation model in SDF format

        >>> from . import vrml
        >>> r = vrml.VRMLReader()
        >>> m = r.read('/home/yosuke/HRP-4C/HRP4Cmain.wrl')
        >>> w = SDFWriter()
        >>> w.write(m, '/tmp/hrp4c.sdf')
        >>> import subprocess
        >>> subprocess.check_call('gz sdf -k /tmp/hrp4c.sdf'.split(' '))
        0
        '''
        # render the data structure using template
        loader = jinja2.PackageLoader(self.__module__, 'template')
        env = jinja2.Environment(loader=loader)

        # render mesh data to each separate collada file
        cwriter = collada.ColladaWriter()
        swriter = stl.STLWriter()
        dirname = os.path.dirname(f)
        for l in m.links:
            for v in l.visuals:
                if v.shapeType == model.ShapeModel.SP_MESH:
                    cwriter.write(v, os.path.join(dirname, v.name + ".dae"))
                    swriter.write(v, os.path.join(dirname, v.name + ".stl"))

        # render mesh collada file for each links
        template = env.get_template('sdf.xml')
        with open(f, 'w') as ofile:
            ofile.write(template.render({
                'model': m,
                'ShapeModel': model.ShapeModel
            }))
