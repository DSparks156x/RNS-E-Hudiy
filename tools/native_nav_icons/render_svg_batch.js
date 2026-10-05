/* Development-only SVG rasterization. Runtime never invokes Node or sharp. */
const fs = require('fs');
const path = require('path');
const sharp = require(process.argv[3] || 'sharp');
async function main() {
  const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  for (const job of jobs) {
    fs.mkdirSync(path.dirname(job.output), {recursive:true});
    const source = fs.readFileSync(job.input,'utf8');
    const width = source.match(/\bwidth="([\d.]+)/);
    if (!width) throw new Error('SVG requires numeric intrinsic width: '+job.input);
    // Render directly at coverage size; never enlarge an intrinsic24px raster.
    const density = 72 * job.size / Number(width[1]);
    await sharp(Buffer.from(source),{density})
      .resize(job.size,job.size,{fit:'contain',background:{r:0,g:0,b:0,alpha:0}})
      .png().toFile(job.output);
  }
  console.log(JSON.stringify({rendered:jobs.length,versions:sharp.versions}));
}
main().catch(error=>{console.error(error);process.exit(1);});
