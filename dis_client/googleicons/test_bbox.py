import os
from PIL import Image

path = 'ic_straight.png'
path = os.path.join('pngs', path)
img = Image.open(path).convert('RGBA')

bbox = img.getbbox(alpha_only=False)
print("Bbox 1:", bbox)
# Sometimes getbbox doesn't work perfectly for alpha if we need alpha channel
# Let's extract alpha and get its bbox
alpha = img.split()[-1]
bbox_alpha = alpha.getbbox()
print("Bbox alpha:", bbox_alpha)

