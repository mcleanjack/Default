"""Regenerate AutoTagDetailComponents.dyn from AutoTagDetailComponents.py.

Usage:  python build_dyn.py
"""
import json
import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "AutoTagDetailComponents.py")
OUTPUT = os.path.join(HERE, "AutoTagDetailComponents.dyn")


def gid(seed):
    return uuid.uuid5(uuid.NAMESPACE_URL, "autotag/" + seed).hex


def port(seed, name, description):
    return {"Id": gid(seed), "Name": name, "Description": description,
            "UsingDefaultValue": False, "Level": 2,
            "UseLevels": False, "KeepListStructure": False}


def bool_node(key, value):
    return {
        "ConcreteType": "CoreNodeModels.Input.BoolSelector, CoreNodeModels",
        "NodeType": "BooleanInputNode", "InputValue": value,
        "Id": gid(key), "Inputs": [],
        "Outputs": [port(key + "/out", "", "Boolean")],
        "Replication": "Disabled", "Description": "Selection between a true and false.",
    }


def number_node(key, value):
    return {
        "ConcreteType": "CoreNodeModels.Input.DoubleInput, CoreNodeModels",
        "NodeType": "NumberInputNode", "NumberType": "Double", "InputValue": value,
        "Id": gid(key), "Inputs": [],
        "Outputs": [port(key + "/out", "", "Double")],
        "Replication": "Disabled", "Description": "Creates a number",
    }


def build():
    with open(SCRIPT) as f:
        code = f.read().replace("\r\n", "\n")

    inputs = [
        ("run", "Run", bool_node("run", True), "boolean", "true"),
        ("offset", "Text offset from guide line (mm on sheet)", number_node("offset", 0.0), "number", "0"),
    ]
    python = {
        "ConcreteType": "PythonNodeModels.PythonNode, PythonNodeModels",
        "NodeType": "PythonScriptNode", "Code": code, "Engine": "CPython3",
        "VariableInputPorts": True, "Id": gid("python"),
        "Inputs": [port("python/in%d" % i, "IN[%d]" % i, "Input #%d" % i) for i in range(len(inputs))],
        "Outputs": [port("python/out", "OUT", "Result of the python script")],
        "Replication": "Disabled", "Description": "Runs an embedded Python script.",
    }
    watch = {
        "ConcreteType": "CoreNodeModels.Watch, CoreNodeModels",
        "NodeType": "ExtensionNode", "Id": gid("watch"),
        "Inputs": [port("watch/in", "", "Node to show output from")],
        "Outputs": [port("watch/out", "", "Node output")],
        "Replication": "Disabled", "Description": "Visualize the node's output",
    }

    nodes = [n for _k, _name, n, _t, _v in inputs] + [python, watch]
    connectors = [
        {"Start": gid(k + "/out"), "End": gid("python/in%d" % i), "Id": gid("conn/" + k), "IsHidden": "False"}
        for i, (k, _n, _node, _t, _v) in enumerate(inputs)
    ] + [{"Start": gid("python/out"), "End": gid("watch/in"), "Id": gid("conn/watch"), "IsHidden": "False"}]

    node_views = [
        {"Id": gid(k), "Name": name, "IsSetAsInput": True, "IsSetAsOutput": False,
         "Excluded": False, "ShowGeometry": True, "X": 0.0, "Y": 120.0 * i}
        for i, (k, name, _n, _t, _v) in enumerate(inputs)
    ] + [
        {"Id": gid("python"), "Name": "Auto Tag Detail Components", "IsSetAsInput": False,
         "IsSetAsOutput": False, "Excluded": False, "ShowGeometry": True, "X": 420.0, "Y": 100.0},
        {"Id": gid("watch"), "Name": "Result", "IsSetAsInput": False, "IsSetAsOutput": True,
         "Excluded": False, "ShowGeometry": True, "X": 760.0, "Y": 100.0},
    ]

    graph = {
        "Uuid": gid("graph"), "IsCustomNode": False,
        "Description": "Pick a vertical guide line, then click detail components; "
                       "Multi-Category tags are created and aligned to the line.",
        "Name": "AutoTagDetailComponents",
        "ElementResolver": {"ResolutionMap": {}},
        "Inputs": [
            {"Id": gid(k), "Name": name, "Type": t, "Value": v,
             "Description": node["Description"]}
            for k, name, node, t, v in inputs
        ],
        "Outputs": [],
        "Nodes": nodes, "Connectors": connectors,
        "Dependencies": [], "NodeLibraryDependencies": [], "Bindings": [],
        "View": {
            "Dynamo": {"ScaleFactor": 1.0, "HasRunWithoutCrash": True,
                       "IsVisibleInDynamoLibrary": True, "Version": "2.12.0.5650",
                       "RunType": "Manual", "RunPeriod": "1000"},
            "Camera": {"Name": "Background Preview", "EyeX": -17.0, "EyeY": 24.0, "EyeZ": 50.0,
                       "LookX": 12.0, "LookY": -13.0, "LookZ": -58.0,
                       "UpX": 0.0, "UpY": 1.0, "UpZ": 0.0},
            "NodeViews": node_views, "Annotations": [],
            "X": 40.0, "Y": 60.0, "Zoom": 1.0,
        },
    }
    with open(OUTPUT, "w", newline="\n") as f:
        json.dump(graph, f, indent=2)
    print("Wrote " + OUTPUT)


if __name__ == "__main__":
    build()
