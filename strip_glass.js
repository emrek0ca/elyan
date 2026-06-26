const fs = require('fs');
const path = require('path');
const cssPath = path.join(__dirname, 'src/renderer/styles.css');
let css = fs.readFileSync(cssPath, 'utf8');

// Remove backdrop-filter lines
css = css.replace(/^\s*-webkit-backdrop-filter:.*?;$/gm, '');
css = css.replace(/^\s*backdrop-filter:.*?;$/gm, '');

// For box-shadow, let's remove any box-shadow that is not 'none' and not an animation keyframe
// Actually, it's safer to just remove all `box-shadow: 0 18px 48px...` style lines but keep simple ones or variables.
// Let's replace `--composer-shadow: .*?` with `--composer-shadow: none;`
// Wait, we already did composer. What else?
// The theme swatches we fixed.
// Modals, sidebars, cards:
css = css.replace(/box-shadow:\s*[^;]*rgba\([^)]+\)[^;]*;/g, 'box-shadow: none;');

fs.writeFileSync(cssPath, css);
console.log('Stripped glass & shadows');
