from PIL import Image

def remove_white_bg(input_path, output_path, threshold=240):
    img = Image.open(input_path).convert("RGBA")
    data = img.getdata()
    
    new_data = []
    for item in data:
        # Check if pixel is close to white
        if item[0] > threshold and item[1] > threshold and item[2] > threshold:
            new_data.append((255, 255, 255, 0)) # transparent
        else:
            new_data.append(item)
            
    img.putdata(new_data)
    img.save(output_path, "PNG")

remove_white_bg("/Users/emrekoca/Desktop/elyan/website/public/robot/image.png", "/Users/emrekoca/Desktop/elyan/website/public/robot/robot_transparent.png")
print("Done")
