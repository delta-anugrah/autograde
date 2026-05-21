from ultralytics import YOLO
files = {"video": ["production.mp4", "top-angle-landscape.mp4", "top-angle-potrait.mp4"], "image": []}

model_version = "v3"
sub_version = "5" # "v?.?"
test_type = "webcam"  #"video" # "image", "video" or "webcam"
file_index = None

if(file_index is None and test_type != "webcam"):
    file_name= ""
    source = f"dataset/test/{test_type}/"
if(test_type== "webcam"):
    file_name= ""
    source = 0
else :
    file_name= files[test_type][file_index]
    source = f"dataset/test/{test_type}/{file_name}"

model = YOLO(f"models/ripe/ripe_{model_version}.{sub_version}.pt")

model.predict(
    source=source,
    conf=0.8,
    show=True if test_type == "images" else True,
    save=True,
    save_txt=False,
    save_conf=False,
    name=f"{model_version}.{sub_version}",
    project=f"test_result/{test_type}/{file_name}",
    exist_ok=True,
    line_width=3,
    device="cpu",
    # stream=True ## stream using camera
)
