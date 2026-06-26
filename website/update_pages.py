import re

files = ['content/site.tr.ts', 'content/site.en.ts']
for f in files:
    with open(f, 'r') as file:
        content = file.read()
    
    content = re.sub(r"key:\s*'desktop',", "key: 'desktop',\n      heroImage: '/desk_focus.png',", content)
    content = re.sub(r"key:\s*'mobile',", "key: 'mobile',\n      heroImage: '/street_flow.png',", content)
    content = re.sub(r"key:\s*'ai',", "key: 'ai',\n      heroImage: '/cozy_night.png',", content)
    content = re.sub(r"key:\s*'support',", "key: 'support',\n      heroImage: '/hero_cafe.png',", content)
    
    with open(f, 'w') as file:
        file.write(content)
