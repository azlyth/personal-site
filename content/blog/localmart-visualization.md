+++
title = "localmart: why, what, and a visualization"
date = 2025-06-28
draft = false
+++

## why & what

For the first couple months of the year, I was working on an idea called **localmart**.

The motivation behind of **localmart** is this:

1. Lots of people today order things from Amazon that they could get in their neighborhood.
2. That means that money is being extracted from local neighborhoods into global corporations.
3. So what if we were able to provide the [Amazon.com](http://Amazon.com) experience, but all the goods are sourced from local stores so that your money gets reinvested into your neighborhood?

So in short, **localmart** is a service where you order local goods from local stores, and it gets delivered within a day or two.

## visualization

I've had a visualization in mind to explain **localmart** to folks, so here's a quick version.

Cash is flowing out to corporations, but with more local orders, cash stays in the neighborhood and makes the neighborhood healthier.

<div id="localmart-visualization" style="width: 100%; height: 600px; border: 2px solid #ddd; border-radius: 8px; margin: 20px 0; position: relative; background: linear-gradient(135deg, #87CEEB 0%, #98FB98 100%);">
    <div id="controls" style="position: absolute; top: 20px; right: 20px; z-index: 100; background: rgba(255,255,255,0.9); padding: 12px; border-radius: 6px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); width: 180px;">
        <div style="margin-bottom: 10px; font-size: 13px; font-weight: 700; color: #333; text-align: center;">Orders in Astoria</div>
        <div style="margin-bottom: 10px; font-size: 12px; color: #444; text-align: center; font-weight: 600;">
            <span id="current-time">June 2025</span>
        </div>
        <div id="money-stats" style="margin-bottom: 10px;">
            <div style="margin-bottom: 6px;">
                <div style="font-size: 11px; font-weight: 600; color: #555; margin-bottom: 1px;">To corporations:</div>
                <div id="money-out" style="font-size: 13px; font-weight: bold; color: #d32f2f; text-align: right;">$0</div>
            </div>
            <div>
                <div style="font-size: 11px; font-weight: 600; color: #555; margin-bottom: 1px;">To neighborhood:</div>
                <div id="money-in" style="font-size: 13px; font-weight: bold; color: #2e7d32; text-align: right;">$0</div>
            </div>
        </div>
        <div>
            <label for="redirect-slider" style="display: block; margin-bottom: 4px; font-size: 11px; color: #555; font-weight: 600;">Local Orders:</label>
            <input type="range" id="redirect-slider" min="0" max="100" value="0" style="width: 100%; margin-bottom: 4px;">
            <div style="font-size: 12px; color: #666; text-align: center; font-weight: 500;"><span id="slider-value">0%</span></div>
        </div>
    </div>
    <canvas id="neighborhood-canvas" style="width: 100%; height: 100%; display: block;"></canvas>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
class NeighborhoodVisualization {
    constructor() {
        this.container = document.getElementById('localmart-visualization');
        this.canvas = document.getElementById('neighborhood-canvas');
        this.redirectSlider = document.getElementById('redirect-slider');
        this.sliderValue = document.getElementById('slider-value');
        this.moneyOutSpan = document.getElementById('money-out');
        this.moneyInSpan = document.getElementById('money-in');
        this.currentTimeSpan = document.getElementById('current-time');
        
        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(75, this.container.offsetWidth / this.container.offsetHeight, 0.1, 1000);
        this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: true });
        
        this.houses = [];
        this.moneyStreams = [];
        this.localStores = [];
        this.redirectionRate = 0; // 0 to 1, how much money stays local
        this.isRedirecting = false;
        
        // Money tracking for cumulative display
        this.corporateMoney = 0;
        this.neighborhoodMoney = 0;
        this.lastUpdateTime = Date.now();
        
        // Time tracking - starting June 2025
        this.currentMonth = 6; // June
        this.currentYear = 2025;
        this.monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        this.lastMonthUpdate = Date.now();
        
        // High-impact visualization economics for Astoria
        // Astoria's estimated Amazon order volume
        this.monthlyAmazonSpending = 5000000; // $5M per month - Astoria's estimated Amazon order volume
        this.monthDurationMs = 2000; // 2 seconds per month
        
        // Flourishing tracking
        this.flourishingLevel = 0; // 0 to 4 levels of flourishing
        this.addedTrees = [];
        this.addedFlowers = [];
        this.addedHouses = [];
        this.addedParks = [];
        this.addedBusinesses = [];
        this.addedCommunitySpaces = [];
        this.ground = null; // Store reference for grass color updates
        
        this.init();
    }
    
    init() {
        // Set up renderer
        this.renderer.setSize(this.container.offsetWidth, this.container.offsetHeight);
        this.renderer.setClearColor(0x87CEEB, 0);
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        
        // Set up camera (fixed isometric view)
        this.camera.position.set(25, 30, 25);
        this.camera.lookAt(0, 0, 0);
        
        // Add lighting
        const ambientLight = new THREE.AmbientLight(0x404040, 0.6);
        this.scene.add(ambientLight);
        
        const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
        directionalLight.position.set(10, 20, 5);
        directionalLight.castShadow = true;
        directionalLight.shadow.mapSize.width = 2048;
        directionalLight.shadow.mapSize.height = 2048;
        this.scene.add(directionalLight);
        
        // Create neighborhood
        this.createGround();
        this.createRoads();
        this.createTrees();
        this.createHouses();
        this.createLocalStores();
        this.createCorporateDistrict();
        
        // Set up controls
        this.redirectSlider.addEventListener('input', (e) => this.onSliderChange(e));
        
        // Start money streams immediately
        this.startMoneyStreams();
        this.createLocalStreams();
        this.localStreamsCreated = true;
        
        // Set initial visibility (all corporate, no local)
        this.updateStreamVisibility();
        
        // Initialize displays
        this.updateTimeDisplay();
        this.updateMoneyDisplay();
        
        // Start animation
        this.animate();
        
        // Handle resize
        window.addEventListener('resize', () => this.onWindowResize());
    }
    
    createGround() {
        const groundGeometry = new THREE.PlaneGeometry(46, 46); // Reduced to match neighborhood size
        const groundMaterial = new THREE.MeshLambertMaterial({ color: 0x8DB360 }); // Start with muted olive grass
        this.ground = new THREE.Mesh(groundGeometry, groundMaterial);
        this.ground.rotation.x = -Math.PI / 2;
        this.ground.receiveShadow = true;
        this.scene.add(this.ground);
    }
    
    createRoads() {
        const roadMaterial = new THREE.MeshLambertMaterial({ color: 0x444444 });
        
        // Create a grid of roads for dense urban layout
        // Horizontal roads (east-west)
        for (let z = -20; z <= 20; z += 8) {
            const road = new THREE.Mesh(new THREE.PlaneGeometry(46, 2.5), roadMaterial);
            road.rotation.x = -Math.PI / 2;
            road.position.set(0, 0.01, z);
            this.scene.add(road);
        }
        
        // Vertical roads (north-south)
        for (let x = -20; x <= 20; x += 8) {
            const road = new THREE.Mesh(new THREE.PlaneGeometry(2.5, 46), roadMaterial);
            road.rotation.x = -Math.PI / 2;
            road.position.set(x, 0.01, 0);
            this.scene.add(road);
        }
        
        // Yellow center lines
        this.createRoadLines();
    }
    
    createRoadLines() {
        const lineMaterial = new THREE.MeshLambertMaterial({ color: 0xFFFF00 });
        
        // Center lines for horizontal roads
        for (let z = -20; z <= 20; z += 8) {
            for (let x = -22; x <= 22; x += 3) {
                const line = new THREE.Mesh(new THREE.PlaneGeometry(2, 0.1), lineMaterial);
                line.rotation.x = -Math.PI / 2;
                line.position.set(x, 0.02, z);
                this.scene.add(line);
            }
        }
        
        // Center lines for vertical roads
        for (let x = -20; x <= 20; x += 8) {
            for (let z = -22; z <= 22; z += 3) {
                const line = new THREE.Mesh(new THREE.PlaneGeometry(0.1, 2), lineMaterial);
                line.rotation.x = -Math.PI / 2;
                line.position.set(x, 0.02, z);
                this.scene.add(line);
            }
        }
    }
    
    createTrees() {
        // Scatter trees throughout the neighborhood more naturally - fill edges
        const treePositions = [
            // Corner trees
            [-22, -22], [-22, 22], [22, -22], [22, 22],
            // Edge trees to fill border completely
            [-22, -15], [-22, -8], [-22, 0], [-22, 8], [-22, 15],
            [22, -15], [22, -8], [22, 0], [22, 8], [22, 15],
            [-15, -22], [-8, -22], [0, -22], [8, -22], [15, -22],
            [-15, 22], [-8, 22], [0, 22], [8, 22], [15, 22],
            // Inner border trees
            [-15, -18], [15, -18], [-15, 18], [15, 18],
            [-18, -10], [-18, 10], [18, -10], [18, 10],
            [-10, -22], [10, -22], [-10, 22], [10, 22],
            [-5, -15], [5, -15], [-5, 15], [5, 15],
            [-22, -5], [-22, 5], [22, -5], [22, 5]
        ];
        
        treePositions.forEach(pos => {
            if (Math.random() > 0.2) { // 80% chance to place a tree for better coverage
                this.createTree(pos[0], pos[1]);
            }
        });
    }
    
    createTree(x, z) {
        const group = new THREE.Group();
        
        // Tree trunk
        const trunkGeometry = new THREE.CylinderGeometry(0.1, 0.15, 1);
        const trunkMaterial = new THREE.MeshLambertMaterial({ color: 0x8B4513 });
        const trunk = new THREE.Mesh(trunkGeometry, trunkMaterial);
        trunk.position.y = 0.5;
        trunk.castShadow = true;
        group.add(trunk);
        
        // Tree foliage
        const foliageGeometry = new THREE.SphereGeometry(0.8, 8, 8);
        const foliageMaterial = new THREE.MeshLambertMaterial({ color: 0x228B22 });
        const foliage = new THREE.Mesh(foliageGeometry, foliageMaterial);
        foliage.position.y = 1.5;
        foliage.castShadow = true;
        group.add(foliage);
        
        group.position.set(x, 0, z);
        this.scene.add(group);
    }
    
    createHouses() {
        // Create dense urban blocks - fill each city block with buildings
        // Skip center area to keep it clear for community spaces
        const blockCenters = [];
        for (let x = -16; x <= 16; x += 8) {
            for (let z = -16; z <= 16; z += 8) {
                // Skip the center square (keep -8 to +8 area clear for flourishing)
                if (Math.abs(x) > 6 || Math.abs(z) > 6) {
                    blockCenters.push([x, z]);
                }
            }
        }
        
        let houseIndex = 0;
        blockCenters.forEach(blockCenter => {
            // Create 4-6 buildings per block in different positions
            const buildingsInBlock = [
                [blockCenter[0] - 2, blockCenter[1] - 2],
                [blockCenter[0] + 2, blockCenter[1] - 2],
                [blockCenter[0] - 2, blockCenter[1] + 2],
                [blockCenter[0] + 2, blockCenter[1] + 2],
                [blockCenter[0], blockCenter[1] - 2.5],
                [blockCenter[0], blockCenter[1] + 2.5]
            ];
            
            buildingsInBlock.forEach(pos => {
                // Double-check to avoid center area completely
                if ((Math.abs(pos[0]) > 7 || Math.abs(pos[1]) > 7) && Math.random() > 0.6) { // 40% chance to place a building (start sparse)
                    const house = this.createHouse(pos[0], pos[1], houseIndex);
                    this.houses.push(house);
                    houseIndex++;
                }
            });
        });
    }
    
    createHouse(x, z, index) {
        const group = new THREE.Group();
        
        // Random building type
        const buildingType = Math.random();
        // Animal Crossing bright primary colors - cozy but vibrant!
        const colors = [
            0xFF6B9D, // Bright pink
            0x4FC3F7, // Bright sky blue
            0xFFB74D, // Orange  
            0x66BB6A, // Bright green
            0xFFEB3B, // Bright yellow
            0xBA68C8, // Bright purple
            0xFF8A65, // Coral
            0x26C6DA, // Bright cyan
            0x8BC34A, // Lime green
            0xF06292, // Hot pink
            0x42A5F5, // Electric blue
            0xFFA726  // Bright orange
        ];
        
        if (buildingType < 0.3) {
            // Apartment building (taller)
            const height = 3 + Math.random() * 2;
            const houseGeometry = new THREE.BoxGeometry(1.8, height, 1.8);
            const houseMaterial = new THREE.MeshLambertMaterial({ color: colors[index % colors.length] });
            const house = new THREE.Mesh(houseGeometry, houseMaterial);
            house.position.y = height / 2;
            house.castShadow = true;
            group.add(house);
            
            // Flat roof with bright colors
            const roofGeometry = new THREE.BoxGeometry(1.9, 0.2, 1.9);
            const roofColors = [0xD84315, 0xFF6F00, 0x8D6E63, 0x5D4037, 0xBF360C]; // Bright warm roof colors
            const roofColor = roofColors[index % roofColors.length];
            const roofMaterial = new THREE.MeshLambertMaterial({ color: roofColor });
            const roof = new THREE.Mesh(roofGeometry, roofMaterial);
            roof.position.y = height + 0.1;
            roof.castShadow = true;
            group.add(roof);
            
            // Add cute chimney for cozy feel
            if (Math.random() > 0.4) { // 60% chance for chimney
                const chimneyGeometry = new THREE.BoxGeometry(0.3, 0.8, 0.3);
                const chimneyMaterial = new THREE.MeshLambertMaterial({ color: 0xD84315 }); // Bright brick red
                const chimney = new THREE.Mesh(chimneyGeometry, chimneyMaterial);
                chimney.position.set(0.6, height + 0.5, 0.6);
                chimney.castShadow = true;
                group.add(chimney);
            }
            
        } else if (buildingType < 0.6) {
            // Row house / townhouse
            const houseGeometry = new THREE.BoxGeometry(1.2, 2, 1.5);
            const houseMaterial = new THREE.MeshLambertMaterial({ color: colors[index % colors.length] });
            const house = new THREE.Mesh(houseGeometry, houseMaterial);
            house.position.y = 1;
            house.castShadow = true;
            group.add(house);
            
            // Slanted roof with bright colors
            const roofGeometry = new THREE.ConeGeometry(1, 0.6, 4);
            const roofColors = [0xD84315, 0xFF6F00, 0x8D6E63, 0x5D4037, 0xBF360C]; // Bright warm roof colors
            const roofColor = roofColors[index % roofColors.length];
            const roofMaterial = new THREE.MeshLambertMaterial({ color: roofColor });
            const roof = new THREE.Mesh(roofGeometry, roofMaterial);
            roof.position.y = 2.3;
            roof.rotation.y = Math.PI / 4;
            roof.castShadow = true;
            group.add(roof);
            
            // Add cute chimney for townhouse
            if (Math.random() > 0.3) { // 70% chance for chimney
                const chimneyGeometry = new THREE.BoxGeometry(0.25, 0.7, 0.25);
                const chimneyMaterial = new THREE.MeshLambertMaterial({ color: 0xD84315 }); // Bright brick red
                const chimney = new THREE.Mesh(chimneyGeometry, chimneyMaterial);
                chimney.position.set(0.4, 2.8, 0.4);
                chimney.castShadow = true;
                group.add(chimney);
            }
            
        } else {
            // Regular house
            const houseGeometry = new THREE.BoxGeometry(1.5, 1.5, 1.5);
            const houseMaterial = new THREE.MeshLambertMaterial({ color: colors[index % colors.length] });
            const house = new THREE.Mesh(houseGeometry, houseMaterial);
            house.position.y = 0.75;
            house.castShadow = true;
            group.add(house);
            
            // Peaked roof with bright colors
            const roofGeometry = new THREE.ConeGeometry(1.2, 0.8, 4);
            const roofColors = [0xD84315, 0xFF6F00, 0x8D6E63, 0x5D4037, 0xBF360C]; // Bright warm roof colors
            const roofColor = roofColors[index % roofColors.length];
            const roofMaterial = new THREE.MeshLambertMaterial({ color: roofColor });
            const roof = new THREE.Mesh(roofGeometry, roofMaterial);
            roof.position.y = 1.9;
            roof.rotation.y = Math.PI / 4;
            roof.castShadow = true;
            group.add(roof);
            
            // Add cute chimney for regular house
            if (Math.random() > 0.5) { // 50% chance for chimney
                const chimneyGeometry = new THREE.BoxGeometry(0.2, 0.6, 0.2);
                const chimneyMaterial = new THREE.MeshLambertMaterial({ color: 0xD84315 }); // Bright brick red
                const chimney = new THREE.Mesh(chimneyGeometry, chimneyMaterial);
                chimney.position.set(0.5, 2.5, 0.5);
                chimney.castShadow = true;
                group.add(chimney);
            }
        }
        
        group.position.set(x, 0, z);
        this.scene.add(group);
        
        return { group, position: { x, z }, moneyGeneration: Math.random() * 0.5 + 0.3 };
    }
    
    createLocalStores() {
        const storeData = [
            { pos: [-14, -10], type: 'coffee', name: 'Cozy Coffee' },
            { pos: [6, -14], type: 'pet', name: 'Pet Paradise' },
            { pos: [-6, 10], type: 'bakery', name: 'Sweet Treats' },
            { pos: [14, 6], type: 'bookstore', name: 'Corner Books' },
            { pos: [-18, 2], type: 'pharmacy', name: 'Local Pharmacy' },
            { pos: [2, -18], type: 'deli', name: 'Neighborhood Deli' },
            { pos: [18, -2], type: 'grocery', name: 'Corner Market' },
            { pos: [-2, 18], type: 'laundry', name: 'Quick Wash' }
        ];
        
        storeData.forEach((data, index) => {
            const store = this.createLocalStore(data.pos[0], data.pos[1], data.type, data.name);
            this.localStores.push(store);
        });
    }
    
    createLocalStore(x, z, type, name) {
        const group = new THREE.Group();
        
        // Store base
        const storeGeometry = new THREE.BoxGeometry(2.5, 2, 2.5);
        let storeColor;
        switch(type) {
            case 'coffee': storeColor = 0x8D6E63; break; // Rich coffee brown
            case 'pet': storeColor = 0xFF6B9D; break; // Bright pink
            case 'bakery': storeColor = 0xFFB74D; break; // Bright orange
            case 'bookstore': storeColor = 0x4FC3F7; break; // Bright sky blue
            case 'pharmacy': storeColor = 0x66BB6A; break; // Bright green
            case 'deli': storeColor = 0xF06292; break; // Hot pink
            case 'grocery': storeColor = 0xBA68C8; break; // Bright purple
            case 'laundry': storeColor = 0x26C6DA; break; // Bright cyan
            default: storeColor = 0x8BC34A; // Lime green
        }
        
        const storeMaterial = new THREE.MeshLambertMaterial({ color: storeColor });
        const store = new THREE.Mesh(storeGeometry, storeMaterial);
        store.position.y = 1;
        store.castShadow = true;
        group.add(store);
        
        // Bright roof
        const roofGeometry = new THREE.ConeGeometry(1.8, 0.6, 4);
        const roofMaterial = new THREE.MeshLambertMaterial({ color: 0x8D6E63 }); // Brighter brown
        const roof = new THREE.Mesh(roofGeometry, roofMaterial);
        roof.position.y = 2.3;
        roof.rotation.y = Math.PI / 4;
        roof.castShadow = true;
        group.add(roof);
        
        // Store sign
        const signGeometry = new THREE.BoxGeometry(2.8, 0.4, 0.1);
        const signMaterial = new THREE.MeshLambertMaterial({ color: 0xF8F8FF });
        const sign = new THREE.Mesh(signGeometry, signMaterial);
        sign.position.y = 2.5;
        sign.position.z = 1.3;
        group.add(sign);
        
        // Add type-specific decorations
        if (type === 'coffee') {
            // Coffee cup decoration
            const cupGeometry = new THREE.CylinderGeometry(0.1, 0.1, 0.2);
            const cupMaterial = new THREE.MeshLambertMaterial({ color: 0xFFFFFF });
            const cup = new THREE.Mesh(cupGeometry, cupMaterial);
            cup.position.set(0.5, 2.7, 1.3);
            group.add(cup);
        } else if (type === 'pet') {
            // Pet bone decoration
            const boneGeometry = new THREE.BoxGeometry(0.3, 0.1, 0.1);
            const boneMaterial = new THREE.MeshLambertMaterial({ color: 0xFFFACD });
            const bone = new THREE.Mesh(boneGeometry, boneMaterial);
            bone.position.set(-0.5, 2.7, 1.3);
            group.add(bone);
        }
        
        group.position.set(x, 0, z);
        this.scene.add(group);
        
        return { group, position: { x, z }, type, name };
    }
    
    createCorporateDistrict() {
        this.corporateBuildings = [];
        
        // Create multiple corporate buildings along the back left edge with more spacing
        const buildingPositions = [
            { x: -40, z: -20, name: 'Amazon' },
            { x: -40, z: -8, name: 'Walmart' },
            { x: -40, z: 4, name: 'Target' },
            { x: -40, z: -32, name: 'Best Buy' },
            { x: -40, z: 16, name: 'Home Depot' }
        ];
        
        buildingPositions.forEach((pos, index) => {
            const building = this.createCorporateBuilding(pos.x, pos.z, pos.name, index);
            this.corporateBuildings.push(building);
        });
        
        // Add "CORPORATIONS" text above the buildings
        this.addCorporationsText();
    }
    
    addCorporationsText() {
        // Create a canvas for the text
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        
        // Set canvas size (larger for better quality at 3x size)
        canvas.width = 1024;
        canvas.height = 256;
        
        // Set text properties (no background fill for transparency)
        context.fillStyle = '#2c3e50';
        context.font = 'bold 120px Arial, sans-serif';
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        
        // Draw the text (no background rectangle)
        context.fillText('CORPORATIONS', canvas.width / 2, canvas.height / 2);
        
        // Create texture from canvas
        const texture = new THREE.CanvasTexture(canvas);
        
        // Create material and geometry for the text
        const textMaterial = new THREE.MeshLambertMaterial({ 
            map: texture,
            transparent: true,
            alphaTest: 0.1
        });
        
        const textGeometry = new THREE.PlaneGeometry(19.2, 4.8); // 80% of previous size
        const textMesh = new THREE.Mesh(textGeometry, textMaterial);
        
        // Position the text above the corporate buildings (adjusted height for bigger sign)
        textMesh.position.set(-40, 17, -8);
        textMesh.lookAt(0, 20, 0); // Make it face towards the neighborhood
        
        this.scene.add(textMesh);
    }
    
    addWindowsToBuilding(group, width, height, depth) {
        const windowMaterial = new THREE.MeshLambertMaterial({ color: 0x87CEEB }); // Light blue windows
        const windowSize = 0.3;
        const windowSpacing = 0.8;
        
        // Calculate how many windows can fit on each side
        const windowsPerRow = Math.floor(width / windowSpacing) - 1;
        const windowRows = Math.floor(height / windowSpacing) - 1;
        
        // Front face windows (facing towards city)
        for (let row = 0; row < windowRows; row++) {
            for (let col = 0; col < windowsPerRow; col++) {
                const windowGeometry = new THREE.BoxGeometry(windowSize, windowSize, 0.05);
                const window = new THREE.Mesh(windowGeometry, windowMaterial);
                
                const x = (col - (windowsPerRow - 1) / 2) * windowSpacing;
                const y = (row - (windowRows - 1) / 2) * windowSpacing + height / 2;
                const z = depth / 2 + 0.025;
                
                window.position.set(x, y, z);
                group.add(window);
            }
        }
        
        // Left side windows
        for (let row = 0; row < windowRows; row++) {
            for (let col = 0; col < windowsPerRow; col++) {
                const windowGeometry = new THREE.BoxGeometry(0.05, windowSize, windowSize);
                const window = new THREE.Mesh(windowGeometry, windowMaterial);
                
                const x = -width / 2 - 0.025;
                const y = (row - (windowRows - 1) / 2) * windowSpacing + height / 2;
                const z = (col - (windowsPerRow - 1) / 2) * windowSpacing;
                
                window.position.set(x, y, z);
                group.add(window);
            }
        }
        
        // Right side windows
        for (let row = 0; row < windowRows; row++) {
            for (let col = 0; col < windowsPerRow; col++) {
                const windowGeometry = new THREE.BoxGeometry(0.05, windowSize, windowSize);
                const window = new THREE.Mesh(windowGeometry, windowMaterial);
                
                const x = width / 2 + 0.025;
                const y = (row - (windowRows - 1) / 2) * windowSpacing + height / 2;
                const z = (col - (windowsPerRow - 1) / 2) * windowSpacing;
                
                window.position.set(x, y, z);
                group.add(window);
            }
        }
    }
    
    createCorporateBuilding(x, z, name, index) {
        const group = new THREE.Group();
        
        // Varying heights and sizes for different corporations (bigger buildings)
        const heights = [12, 10, 11, 9, 14];
        const widths = [6, 5.5, 7, 5, 8];
        // Softer corporate colors - still professional but less harsh
        const colors = [0x4A5568, 0x5A6C7D, 0x6B7280, 0x718096, 0x2D3748];
        
        const height = heights[index % heights.length];
        const width = widths[index % widths.length];
        const color = colors[index % colors.length];
        
        // Corporate building (tall, imposing, bigger)
        const buildingGeometry = new THREE.BoxGeometry(width, height, width);
        const buildingMaterial = new THREE.MeshLambertMaterial({ color });
        const building = new THREE.Mesh(buildingGeometry, buildingMaterial);
        building.position.y = height / 2;
        building.castShadow = true;
        group.add(building);
        
        // Add windows to the building
        this.addWindowsToBuilding(group, width, height, width);
        
        // Corporate logo area (facing towards the city)
        const logoGeometry = new THREE.BoxGeometry(width + 0.1, 1.5, 0.1);
        const logoColors = [0xf39c12, 0x3498db, 0xe74c3c, 0xffff00, 0xff6600];
        const logoMaterial = new THREE.MeshLambertMaterial({ color: logoColors[index % logoColors.length] });
        const logo = new THREE.Mesh(logoGeometry, logoMaterial);
        logo.position.y = height - 1.5;
        logo.position.z = -(width / 2 + 0.05); // Negative Z to face towards the city
        group.add(logo);
        
        group.position.set(x, 0, z);
        this.scene.add(group);
        
        return { group, position: { x, z }, name };
    }
    
    createMoneyStream(fromPos, toPos, color = 0xf1c40f, isLocal = false) {
        const stream = {
            particles: [],
            fromPos,
            toPos,
            color,
            active: true,
            isLocal
        };
        
        // Create particles for the stream (bigger dollar bill-like particles)
        for (let i = 0; i < 4; i++) {
            // Create a flatter rectangular shape for dollar bills (bigger and more visible)
            const geometry = new THREE.BoxGeometry(0.6, 0.3, 0.05);
            const material = new THREE.MeshLambertMaterial({ 
                color,
                transparent: false,
                opacity: 1.0
            });
            const particle = new THREE.Mesh(geometry, material);
            particle.castShadow = true;
            
            const progress = i / 4;
            particle.position.lerpVectors(
                new THREE.Vector3(fromPos.x, 2, fromPos.z),
                new THREE.Vector3(toPos.x, 6, toPos.z),
                progress
            );
            
            // Add some rotation for animation
            particle.userData = { 
                progress, 
                speed: 0.008 + Math.random() * 0.005,
                rotationSpeed: (Math.random() - 0.5) * 0.15,
                initialRotation: Math.random() * Math.PI * 2
            };
            
            stream.particles.push(particle);
            this.scene.add(particle);
        }
        
        return stream;
    }
    
    updateMoneyStreams() {
        // Calculate time once per frame instead of per particle
        const time = Date.now() * 0.001;
        
        // Reuse Vector3 objects to avoid creating new ones every frame
        if (!this.tempFromPos) {
            this.tempFromPos = new THREE.Vector3();
            this.tempToPos = new THREE.Vector3();
        }
        
        this.moneyStreams.forEach(stream => {
            if (!stream.active) return;
            
            // Set up positions once per stream
            this.tempFromPos.set(stream.fromPos.x, 2, stream.fromPos.z);
            this.tempToPos.set(stream.toPos.x, 6, stream.toPos.z);
            
            stream.particles.forEach(particle => {
                particle.userData.progress += particle.userData.speed;
                
                if (particle.userData.progress > 1) {
                    particle.userData.progress = 0;
                }
                
                particle.position.lerpVectors(this.tempFromPos, this.tempToPos, particle.userData.progress);
                
                // Add some curve to the trajectory (higher arc)
                particle.position.y += Math.sin(particle.userData.progress * Math.PI) * 3;
                
                // Animate rotation for dollar bill effect (using cached time)
                particle.rotation.z = particle.userData.initialRotation + time * particle.userData.rotationSpeed;
                particle.rotation.y = Math.sin(time * 2 + particle.userData.initialRotation) * 0.3;
            });
        });
    }
    
    startMoneyStreams() {
        this.houses.forEach(house => {
            // Randomly select a corporate building to send money to
            const randomCorp = this.corporateBuildings[Math.floor(Math.random() * this.corporateBuildings.length)];
            const corpStream = this.createMoneyStream(
                house.position,
                randomCorp.position,
                0x2ecc71 // Green for all money
            );
            this.moneyStreams.push(corpStream);
        });
    }
    
    onSliderChange(event) {
        const value = parseInt(event.target.value);
        this.sliderValue.textContent = value + '%';
        
        // Set redirection rate based on slider (0-100% -> 0-1.0)
        this.redirectionRate = value / 100;
        this.updateRedirection();
        
        // Update stream visibility to show correct proportion
        this.updateStreamVisibility();
    }
    
    updateMoneyAccumulation() {
        const currentTime = Date.now();
        const deltaTime = (currentTime - this.lastUpdateTime) / 1000; // Convert to seconds
        this.lastUpdateTime = currentTime;
        
        // High-impact money flow: $6M per month over 3 seconds
        // $6M / 3 seconds = $2M per second for dramatic visual impact
        const moneyPerSecond = this.monthlyAmazonSpending / (this.monthDurationMs / 1000);
        
        // Distribute money based on redirection rate
        const corporateFlow = moneyPerSecond * (1 - this.redirectionRate) * deltaTime;
        const neighborhoodFlow = moneyPerSecond * this.redirectionRate * deltaTime;
        
        this.corporateMoney += corporateFlow;
        this.neighborhoodMoney += neighborhoodFlow;
        
        // Update time progression (advance 1 month every 3 seconds of real time)
        if (currentTime - this.lastMonthUpdate > this.monthDurationMs) {
            this.advanceMonth();
            this.lastMonthUpdate = currentTime;
        }
        
        // Update display periodically (every ~100ms for smooth updates)
        if (currentTime % 100 < 50) {
            this.updateMoneyDisplay();
            this.updateTimeDisplay();
            
            // Check for flourishing changes as money accumulates
            this.updateNeighborhoodFlourishing();
        }
    }
    
    addFlourishingTrees(count) {
        const possiblePositions = [
            // TREES - Avoiding all community spaces
            // Community space exclusions:
            // - Plaza area [0,0] ± 3 units  
            // - Garden area [-4,4] ± 3 units
            // - West Park [-15,-15] ± 4 units  
            // - East Park [15,15] ± 4 units
            // - Legacy basketball [0,-12] ± 3 units
            
            // Safe edge positions
            [-18, -10], [18, -10], [-10, -18], [10, -18],
            [-18, 10], [18, 10], [-10, 18], [10, 18],
            [-18, -6], [18, -6], [-6, -18], [6, -18],
            [-18, 6], [18, 6], [-6, 18], [6, 18],
            [-18, -2], [18, -2], [-2, -18], [2, -18],
            [-18, 2], [18, 2], [-2, 18], [2, 18],
            // Additional safe edge trees
            [-16, -18], [16, -18], [-18, -16], [18, -16],
            [-16, 18], [16, 18], [-18, 16], [18, 16],
            [-14, -18], [14, -18], [-18, -14], [18, -14],
            [-14, 18], [14, 18], [-18, 14], [18, 14],
            [-12, -18], [12, -18], [-18, -12], [18, -12],
            [-12, 18], [12, 18], [-18, 12], [18, 12],
            // Safe inner positions (avoiding community spaces)
            [-9, -16], [9, -16], [-16, -9], [16, -9],
            [-9, 16], [9, 16], [-16, 9], [16, 9],
            [-5, -18], [5, -18], [-18, -5], [18, -5],
            [-5, 18], [5, 18], [-18, 5], [18, 5],
            // Additional safe coverage
            [-8, -18], [8, -18], [-18, -8], [18, -8],
            [-8, 18], [8, 18], [-18, 8], [18, 8],
            // Corners away from parks
            [-19, -9], [19, -9], [-9, -19], [9, -19],
            [-19, 9], [19, 9], [-9, 19], [9, 19],
            // Far corners  
            [-19, -5], [19, -5], [-5, -19], [5, -19],
            [-19, 5], [19, 5], [-5, 19], [5, 19],
            // Safe mid-edge positions
            [-17, -7], [17, -7], [-7, -17], [7, -17],
            [-17, 7], [17, 7], [-7, 17], [7, 17]
        ];
        
        for (let i = 0; i < count && this.addedTrees.length < possiblePositions.length; i++) {
            const pos = possiblePositions[this.addedTrees.length];
            this.createTree(pos[0], pos[1]);
            this.addedTrees.push(pos);
        }
    }
    
    addFlowers(count) {
        const flowerPositions = [
            // FLOWERS - Avoiding all community spaces
            // Community space exclusions:
            // - Plaza area [0,0] ± 3 units (x: -3 to 3, z: -3 to 3)
            // - Garden area [-4,4] ± 3 units (x: -7 to -1, z: 1 to 7)  
            // - West Park [-15,-15] ± 4 units (x: -19 to -11, z: -19 to -11)
            // - East Park [15,15] ± 4 units (x: 11 to 19, z: 11 to 19)
            // - Legacy basketball [0,-12] ± 3 units (x: -3 to 3, z: -15 to -9)
            
            // Safe edge positions - avoiding all exclusion zones
            [-18, -8], [18, -8], [-8, -18], [8, -18],
            [-18, 8], [18, 8], [-8, 18], [8, 18],
            [-16, -6], [16, -6], [-6, -16], [6, -16],
            [-16, 6], [16, 6], [-6, 18], [6, 18],
            [-5, -17], [5, -17], [-17, -5], [17, -5],
            [-5, 17], [5, 17], [-17, 5], [17, 5],
            // Safe positions away from community spaces
            [-10, -18], [10, -18], [-18, -10], [18, -10],
            [-18, 10], [18, 10], [-10, 18], [10, 18],
            [-16, -2], [16, -2], [-16, 2], [16, 2],
            [-18, -2], [18, -2], [-18, 2], [18, 2],
            [-18, -6], [18, -6], [-6, -18], [6, -18],
            [-18, 6], [18, 6], [-6, 16], [6, 16],
            [-19, -9], [19, -9], [-9, -19], [9, -19],
            [-19, 9], [19, 9], [-9, 19], [9, 19],
            [-18, -12], [18, -12], [-12, -18], [12, -18],
            [-18, 12], [18, 12], [-12, 18], [12, 18],
            [-19, -7], [19, -7], [-7, -19], [7, -19],
            [-19, 7], [19, 7], [-7, 17], [7, 17],
            [-19, -5], [19, -5], [-5, -19], [5, -19],
            [-19, 5], [19, 5], [-5, 17], [5, 17],
            [-19, -3], [19, -3], [-19, 3], [19, 3],
            // Safe mid-range positions
            [-17, -7], [17, -7], [-7, -17], [7, -17],
            [-17, 7], [17, 7],
            // Safe scattered positions throughout non-excluded areas
            [-10, -6], [10, -6], [-10, 6], [10, 6],
            [-14, -8], [14, -8], [-8, -17], [8, -17],
            [-14, 8], [14, 8], [-8, 17], [8, 17],
            [-12, -6], [12, -6], [-12, 6], [12, 6],
            [-16, -10], [16, -10], [-10, -16], [10, -16],
            [-16, 10], [16, 10], [-10, 16], [10, 16],
            // Additional safe flower positions
            [-9, -17], [9, -17], [-17, -9], [17, -9],
            [-9, 17], [9, 17], [-17, 9], [17, 9],
            [-8, -16], [8, -16], [-16, -8], [16, -8],
            [-8, 16], [8, 16], [-16, 8], [16, 8]
        ];
        
        for (let i = 0; i < count && this.addedFlowers.length < flowerPositions.length; i++) {
            const pos = flowerPositions[this.addedFlowers.length];
            this.createFlower(pos[0], pos[1]);
            this.addedFlowers.push(pos);
        }
    }
    
    addNewBusinesses(count) {
        const businessPositions = [
            // Strategic business locations - avoiding all community spaces
            // Community space exclusions:
            // - Plaza [0,0] ± 3, Garden [-4,4] ± 3, West Park [-15,-15] ± 4, East Park [15,15] ± 4, Basketball [0,-12] ± 3
            [-10, -14], [10, -14], [-14, -10], [14, -10],
            [-6, -18], [6, -18], [-18, -6], [18, -6],
            [-16, -2], [16, -2], // Removed conflicting positions near plaza/garden
            [-14, -6], [14, -6], [-6, -14], [6, -14], 
            [-18, -10], [18, -10], [-10, -18], [10, -18],
            [-12, -16], [12, -16], [-16, -12], [16, -12],
            [-8, -2], [8, -2], // Moved away from plaza area
            [-18, -8], [18, -8], [-8, -18], [8, -18], // Safe edge positions
            [-14, -2], [14, -2], [-2, -14], [2, -14], // Safe from all community spaces
            [-10, -16], [10, -16], [-16, -10], [16, -10] // Additional safe business spots
        ];
        
        const businessTypes = [
            { type: 'restaurant', name: 'Local Bistro', color: 0xFF6B9D }, // Bright pink
            { type: 'cafe', name: 'Corner Café', color: 0x8D6E63 }, // Rich coffee brown
            { type: 'fitness', name: 'Neighborhood Gym', color: 0x42A5F5 }, // Electric blue
            { type: 'boutique', name: 'Local Boutique', color: 0xBA68C8 }, // Bright purple
            { type: 'hardware', name: 'Hardware Store', color: 0xFFEB3B }, // Bright yellow
            { type: 'florist', name: 'Flower Shop', color: 0xFF8A65 }, // Coral
            { type: 'artgallery', name: 'Art Gallery', color: 0x26C6DA }, // Bright cyan
            { type: 'music', name: 'Music Store', color: 0xF06292 }, // Hot pink
            { type: 'wellness', name: 'Wellness Center', color: 0x66BB6A }, // Bright green
            { type: 'coworking', name: 'Co-working Space', color: 0xFFA726 } // Bright orange
        ];
        
        for (let i = 0; i < count && this.addedBusinesses.length < businessPositions.length; i++) {
            const pos = businessPositions[this.addedBusinesses.length];
            const businessData = businessTypes[this.addedBusinesses.length % businessTypes.length];
            const business = this.createNewBusiness(pos[0], pos[1], businessData);
            this.addedBusinesses.push({ business, position: pos, type: businessData.type });
        }
    }
    
    createNewBusiness(x, z, businessData) {
        const group = new THREE.Group();
        
        // Business building - slightly larger than houses
        const buildingGeometry = new THREE.BoxGeometry(2.2, 2.5, 2.2);
        const buildingMaterial = new THREE.MeshLambertMaterial({ color: businessData.color });
        const building = new THREE.Mesh(buildingGeometry, buildingMaterial);
        building.position.y = 1.25;
        building.castShadow = true;
        group.add(building);
        
        // Flat commercial roof with cozy colors
        const roofGeometry = new THREE.BoxGeometry(2.3, 0.2, 2.3);
        const roofColors = [0x8B4513, 0xA0522D, 0xCD853F, 0xD2691E, 0xBC8F8F];
        const roofColor = roofColors[Math.floor(Math.random() * roofColors.length)];
        const roofMaterial = new THREE.MeshLambertMaterial({ color: roofColor });
        const roof = new THREE.Mesh(roofGeometry, roofMaterial);
        roof.position.y = 2.6;
        roof.castShadow = true;
        group.add(roof);
        
        // Simple business sign
        const signGeometry = new THREE.BoxGeometry(1.8, 0.3, 0.1);
        const signMaterial = new THREE.MeshLambertMaterial({ color: 0xFFFFFF });
        const sign = new THREE.Mesh(signGeometry, signMaterial);
        sign.position.y = 2.0;
        sign.position.z = 1.15;
        group.add(sign);
        
        group.position.set(x, 0, z);
        this.scene.add(group);
        
        return { group, name: businessData.name, type: businessData.type };
    }
    
    addCommunityGarden() {
        // Find a good central location for the community garden
        const gardenPosition = [-4, 4]; // Nice central spot
        const garden = this.createCommunityGarden(gardenPosition[0], gardenPosition[1]);
        this.addedCommunitySpaces.push({ element: garden, type: 'garden', position: gardenPosition });
    }
    
    createCommunityGarden(x, z) {
        const group = new THREE.Group();
        
        // Garden plots (raised beds)
        for (let i = 0; i < 6; i++) {
            const plotGeometry = new THREE.BoxGeometry(1.5, 0.2, 0.8);
            const plotMaterial = new THREE.MeshLambertMaterial({ color: 0x8B4513 });
            const plot = new THREE.Mesh(plotGeometry, plotMaterial);
            
            const plotX = (i % 3 - 1) * 2;
            const plotZ = Math.floor(i / 3) * 1.5 - 0.75;
            plot.position.set(plotX, 0.1, plotZ);
            group.add(plot);
            
            // Plants in each plot
            for (let j = 0; j < 3; j++) {
                const plantGeometry = new THREE.SphereGeometry(0.1, 6, 6);
                const plantColors = [0x2ECC71, 0x27AE60, 0x16A085];
                const plantMaterial = new THREE.MeshLambertMaterial({ color: plantColors[j % 3] });
                const plant = new THREE.Mesh(plantGeometry, plantMaterial);
                plant.position.set(plotX + (j - 1) * 0.4, 0.3, plotZ);
                group.add(plant);
            }
        }
        
        // Garden shed
        const shedGeometry = new THREE.BoxGeometry(1.2, 1.5, 1.0);
        const shedMaterial = new THREE.MeshLambertMaterial({ color: 0x8B4513 });
        const shed = new THREE.Mesh(shedGeometry, shedMaterial);
        shed.position.set(3, 0.75, 0);
        group.add(shed);
        
        group.position.set(x, 0, z);
        this.scene.add(group);
        
        return group;
    }
    
    addPublicPlaza() {
        // Central plaza location
        const plazaPosition = [0, 0]; // Dead center of neighborhood
        const plaza = this.createPublicPlaza(plazaPosition[0], plazaPosition[1]);
        this.addedCommunitySpaces.push({ element: plaza, type: 'plaza', position: plazaPosition });
    }
    
    createPublicPlaza(x, z) {
        const group = new THREE.Group();
        
        // Plaza base - circular paved area
        const plazaGeometry = new THREE.CylinderGeometry(4, 4, 0.1, 16);
        const plazaMaterial = new THREE.MeshLambertMaterial({ color: 0xBDC3C7 });
        const plaza = new THREE.Mesh(plazaGeometry, plazaMaterial);
        plaza.position.y = 0.05;
        group.add(plaza);
        
        // Central fountain
        const fountainBaseGeometry = new THREE.CylinderGeometry(1, 1, 0.5, 12);
        const fountainMaterial = new THREE.MeshLambertMaterial({ color: 0x85929E });
        const fountainBase = new THREE.Mesh(fountainBaseGeometry, fountainMaterial);
        fountainBase.position.y = 0.35;
        group.add(fountainBase);
        
        const fountainTopGeometry = new THREE.CylinderGeometry(0.3, 0.3, 0.8, 8);
        const fountainTop = new THREE.Mesh(fountainTopGeometry, fountainMaterial);
        fountainTop.position.y = 0.9;
        group.add(fountainTop);
        
        // Surrounding benches in a circle
        for (let i = 0; i < 6; i++) {
            const angle = (i / 6) * Math.PI * 2;
            const benchX = Math.cos(angle) * 3;
            const benchZ = Math.sin(angle) * 3;
            
            const benchGroup = new THREE.Group();
            
            // Bench
            const seatGeometry = new THREE.BoxGeometry(1.2, 0.1, 0.4);
            const seatMaterial = new THREE.MeshLambertMaterial({ color: 0x8B4513 });
            const seat = new THREE.Mesh(seatGeometry, seatMaterial);
            seat.position.y = 0.3;
            benchGroup.add(seat);
            
            benchGroup.position.set(benchX, 0, benchZ);
            benchGroup.rotation.y = angle + Math.PI/2; // Face the fountain
            group.add(benchGroup);
        }
        
        // Decorative lampposts
        for (let i = 0; i < 4; i++) {
            const angle = (i / 4) * Math.PI * 2 + Math.PI/4;
            const lampX = Math.cos(angle) * 3.5;
            const lampZ = Math.sin(angle) * 3.5;
            
            const lampGeometry = new THREE.CylinderGeometry(0.05, 0.05, 2.5);
            const lampMaterial = new THREE.MeshLambertMaterial({ color: 0x2C3E50 });
            const lamp = new THREE.Mesh(lampGeometry, lampMaterial);
            lamp.position.set(lampX, 1.25, lampZ);
            group.add(lamp);
            
            // Lamp light
            const lightGeometry = new THREE.SphereGeometry(0.2, 8, 8);
            const lightMaterial = new THREE.MeshLambertMaterial({ color: 0xF1C40F });
            const light = new THREE.Mesh(lightGeometry, lightMaterial);
            light.position.set(lampX, 2.3, lampZ);
            group.add(light);
        }
        
        group.position.set(x, 0, z);
        this.scene.add(group);
        
        return group;
    }
    
    createBench(x, z, rotation = 0) {
        const group = new THREE.Group();
        
        // Bench seat
        const seatGeometry = new THREE.BoxGeometry(1.2, 0.1, 0.4);
        const seatMaterial = new THREE.MeshLambertMaterial({ color: 0x8B4513 });
        const seat = new THREE.Mesh(seatGeometry, seatMaterial);
        seat.position.y = 0.3;
        group.add(seat);
        
        // Bench back
        const backGeometry = new THREE.BoxGeometry(1.2, 0.5, 0.1);
        const back = new THREE.Mesh(backGeometry, seatMaterial);
        back.position.y = 0.55;
        back.position.z = -0.15;
        group.add(back);
        
        // Bench legs
        for (let i = 0; i < 4; i++) {
            const legGeometry = new THREE.BoxGeometry(0.1, 0.3, 0.1);
            const leg = new THREE.Mesh(legGeometry, seatMaterial);
            leg.position.x = (i % 2 === 0) ? -0.5 : 0.5;
            leg.position.z = (i < 2) ? 0.15 : -0.15;
            leg.position.y = 0.15;
            group.add(leg);
        }
        
        group.position.set(x, 0, z);
        group.rotation.y = rotation;
        this.scene.add(group);
        
        return group;
    }
    
    createBasketballCourt(x, z) {
        const group = new THREE.Group();
        
        // Court surface
        const courtGeometry = new THREE.PlaneGeometry(6, 4);
        const courtMaterial = new THREE.MeshLambertMaterial({ color: 0x8B4513 });
        const court = new THREE.Mesh(courtGeometry, courtMaterial);
        court.rotation.x = -Math.PI / 2;
        court.position.y = 0.01;
        group.add(court);
        
        // Court lines
        const lineMaterial = new THREE.MeshLambertMaterial({ color: 0xFFFFFF });
        
        // Center line
        const centerLineGeometry = new THREE.PlaneGeometry(0.1, 4);
        const centerLine = new THREE.Mesh(centerLineGeometry, lineMaterial);
        centerLine.rotation.x = -Math.PI / 2;
        centerLine.position.y = 0.02;
        group.add(centerLine);
        
        // Basketball hoops
        for (let i = 0; i < 2; i++) {
            const hoopGroup = new THREE.Group();
            
            // Hoop pole
            const poleGeometry = new THREE.CylinderGeometry(0.1, 0.1, 2.5);
            const poleMaterial = new THREE.MeshLambertMaterial({ color: 0x666666 });
            const pole = new THREE.Mesh(poleGeometry, poleMaterial);
            pole.position.y = 1.25;
            hoopGroup.add(pole);
            
            // Hoop rim
            const rimGeometry = new THREE.TorusGeometry(0.3, 0.05, 8, 16);
            const rimMaterial = new THREE.MeshLambertMaterial({ color: 0xFF6600 });
            const rim = new THREE.Mesh(rimGeometry, rimMaterial);
            rim.position.y = 2.3;
            rim.rotation.x = Math.PI / 2;
            hoopGroup.add(rim);
            
            hoopGroup.position.x = i === 0 ? -2.8 : 2.8;
            group.add(hoopGroup);
        }
        
        group.position.set(x, 0, z);
        this.scene.add(group);
        
        return group;
    }
    
    createSculpture(x, z, type) {
        const group = new THREE.Group();
        
        // Sculpture base
        const baseGeometry = new THREE.CylinderGeometry(0.8, 0.8, 0.2);
        const baseMaterial = new THREE.MeshLambertMaterial({ color: 0x999999 });
        const base = new THREE.Mesh(baseGeometry, baseMaterial);
        base.position.y = 0.1;
        group.add(base);
        
        // Different sculpture types
        const sculptureColors = [0x2E86AB, 0xA23B72, 0xF18F01, 0xC73E1D, 0x592E83];
        const sculptureColor = sculptureColors[type % sculptureColors.length];
        const sculptureMaterial = new THREE.MeshLambertMaterial({ color: sculptureColor });
        
        if (type === 0) {
            // Abstract tall sculpture
            const sculptureGeometry = new THREE.BoxGeometry(0.3, 1.5, 0.3);
            const sculpture = new THREE.Mesh(sculptureGeometry, sculptureMaterial);
            sculpture.position.y = 1;
            sculpture.rotation.y = Math.PI / 4;
            group.add(sculpture);
        } else if (type === 1) {
            // Sphere sculpture
            const sculptureGeometry = new THREE.SphereGeometry(0.4, 8, 8);
            const sculpture = new THREE.Mesh(sculptureGeometry, sculptureMaterial);
            sculpture.position.y = 0.6;
            group.add(sculpture);
        } else {
            // Abstract twisted sculpture
            const sculptureGeometry = new THREE.ConeGeometry(0.4, 1.2, 6);
            const sculpture = new THREE.Mesh(sculptureGeometry, sculptureMaterial);
            sculpture.position.y = 0.8;
            sculpture.rotation.z = Math.PI / 6;
            group.add(sculpture);
        }
        
        group.position.set(x, 0, z);
        this.scene.add(group);
        
        return group;
    }
    
    addPublicPark() {
        // Define two distinct park locations
        const parkLocations = [
            { 
                center: { x: -15, z: -15 }, 
                name: 'West Park',
                elements: [
                    { type: 'trees', positions: [{ x: -17, z: -17 }, { x: -13, z: -17 }, { x: -15, z: -13 }] },
                    { type: 'benches', positions: [{ x: -15, z: -15, rotation: 0 }, { x: -17, z: -13, rotation: Math.PI/4 }] },
                    { type: 'flowers', positions: [{ x: -16, z: -14 }, { x: -14, z: -16 }, { x: -13, z: -14 }] },
                    { type: 'sculpture', position: { x: -15, z: -17 } }
                ]
            },
            { 
                center: { x: 15, z: 15 }, 
                name: 'East Park',
                elements: [
                    { type: 'trees', positions: [{ x: 17, z: 17 }, { x: 13, z: 17 }, { x: 15, z: 13 }] },
                    { type: 'benches', positions: [{ x: 15, z: 15, rotation: Math.PI }, { x: 17, z: 13, rotation: -Math.PI/4 }] },
                    { type: 'flowers', positions: [{ x: 16, z: 14 }, { x: 14, z: 16 }, { x: 13, z: 14 }, { x: 17, z: 15 }] },
                    { type: 'basketball', position: { x: 15, z: 17 } }
                ]
            }
        ];
        
        // Determine which park to add based on current park count
        const currentParkCount = this.addedParks.filter(p => p.type === 'park').length;
        if (currentParkCount >= 2) return; // Max 2 parks
        
        const parkToAdd = parkLocations[currentParkCount];
        const parkGroup = new THREE.Group();
        
        // Apply current investment scale
        const maxScaleInvestment = 10000000;
        const investmentProgress = Math.min(this.neighborhoodMoney / maxScaleInvestment, 1.0);
        const parkScale = 1.0 + (investmentProgress * 0.10);
        
        // Store park elements for scaling
        const parkElements = [];
        
        // Add all park elements
        parkToAdd.elements.forEach(elementGroup => {
            switch (elementGroup.type) {
                case 'trees':
                    elementGroup.positions.forEach(pos => {
                        this.createTree(pos.x, pos.z); // Trees add themselves to scene
                        // Find the just-added tree in the scene for scaling
                        const addedTree = this.scene.children[this.scene.children.length - 1];
                        addedTree.scale.set(parkScale, parkScale, parkScale);
                        parkElements.push(addedTree);
                    });
                    break;
                    
                case 'benches':
                    elementGroup.positions.forEach(pos => {
                        const bench = this.createBench(pos.x, pos.z, pos.rotation || 0);
                        bench.scale.set(parkScale, parkScale, parkScale);
                        this.addedParks.push({ type: 'bench', element: bench });
                        parkElements.push(bench);
                    });
                    break;
                    
                case 'flowers':
                    elementGroup.positions.forEach(pos => {
                        this.createFlower(pos.x, pos.z); // Flowers are added directly to scene
                    });
                    break;
                    
                case 'sculpture':
                    const sculpture = this.createSculpture(elementGroup.position.x, elementGroup.position.z, currentParkCount);
                    sculpture.scale.set(parkScale, parkScale, parkScale);
                    this.addedParks.push({ type: 'sculpture', element: sculpture });
                    parkElements.push(sculpture);
                    break;
                    
                case 'basketball':
                    const court = this.createBasketballCourt(elementGroup.position.x, elementGroup.position.z);
                    court.scale.set(parkScale, parkScale, parkScale);
                    this.addedParks.push({ type: 'basketball', element: court });
                    parkElements.push(court);
                    break;
            }
        });
        
        // Track that we've added a park with its elements
        this.addedParks.push({ type: 'park', name: parkToAdd.name, elements: parkElements });
    }
    
    addParkElements(benchCount, hasBasketballCourt, sculptureCount) {
        // Legacy function for individual park elements
        const benchPositions = [
            { x: -12, z: -18, rotation: 0 },
            { x: 12, z: -18, rotation: Math.PI },
            { x: -18, z: -12, rotation: Math.PI / 2 },
            { x: 18, z: -12, rotation: -Math.PI / 2 },
        ];
        
        const maxScaleInvestment = 10000000;
        const investmentProgress = Math.min(this.neighborhoodMoney / maxScaleInvestment, 1.0);
        const parkScale = 1.0 + (investmentProgress * 0.10);
        
        // Add individual benches
        for (let i = 0; i < benchCount && i < benchPositions.length; i++) {
            const pos = benchPositions[i];
            const bench = this.createBench(pos.x, pos.z, pos.rotation);
            bench.scale.set(parkScale, parkScale, parkScale);
            this.addedParks.push({ type: 'bench', element: bench });
        }
        
        // Add basketball court
        if (hasBasketballCourt && !this.addedParks.some(p => p.type === 'basketball')) {
            const court = this.createBasketballCourt(0, -12);
            court.scale.set(parkScale, parkScale, parkScale);
            this.addedParks.push({ type: 'basketball', element: court });
        }
        
        // Add sculptures
        const sculpturePositions = [
            { x: -8, z: -8 }, { x: 8, z: -8 }
        ];
        
        for (let i = 0; i < sculptureCount && i < sculpturePositions.length; i++) {
            const pos = sculpturePositions[i];
            const sculpture = this.createSculpture(pos.x, pos.z, i);
            sculpture.scale.set(parkScale, parkScale, parkScale);
            this.addedParks.push({ type: 'sculpture', element: sculpture });
        }
    }
    
    createFlower(x, z) {
        const group = new THREE.Group();
        
        // Flower stem
        const stemGeometry = new THREE.CylinderGeometry(0.02, 0.02, 0.3);
        const stemMaterial = new THREE.MeshLambertMaterial({ color: 0x228B22 });
        const stem = new THREE.Mesh(stemGeometry, stemMaterial);
        stem.position.y = 0.15;
        group.add(stem);
        
        // Flower petals
        const petalColors = [0xFF69B4, 0xFF1493, 0xFFB6C1, 0xFF6347, 0xFFA500];
        const petalGeometry = new THREE.SphereGeometry(0.08, 6, 6);
        const petalMaterial = new THREE.MeshLambertMaterial({ 
            color: petalColors[Math.floor(Math.random() * petalColors.length)] 
        });
        const petals = new THREE.Mesh(petalGeometry, petalMaterial);
        petals.position.y = 0.35;
        group.add(petals);
        
        group.position.set(x, 0, z);
        this.scene.add(group);
    }
    
    addNewHouses(count) {
        const emptySpots = [
            // CONTAINED within street grid boundaries (-18 to 18)
            // EXCLUDE center area (-7 to +7) to keep community spaces clear
            // Core positions around existing blocks
            [-18, -6], [18, -6], [-6, -18], [6, -18],
            [-18, 6], [18, 6], [-6, 18], [6, 18],
            [-14, -14], [14, -14], [-14, 14], [14, 14],
            // Fill within each city block (avoiding center)
            [-10, -6], [10, -6], [-10, 6], [10, 6],
            [-2, -14], [2, -14], [-14, -2], [14, -2],
            [-2, 14], [2, 14], [-14, 2], [14, 2],
            [-16, 0], [16, 0], [0, -16], [0, 16],
            [-8, -8], [8, -8], [-8, 8], [8, 8],
            // Dense infill within blocks (avoiding center)
            [-12, 0], [12, 0], [0, -12], [0, 12],
            // Fill all remaining block spaces
            [-18, -10], [18, -10], [-10, -18], [10, -18],
            [-18, 10], [18, 10], [-10, 18], [10, 18],
            [-16, -8], [16, -8], [-8, -16], [8, -16],
            [-16, 8], [16, 8], [-8, 16], [8, 16],
            [-18, -2], [18, -2], [-2, -18], [2, -18],
            [-18, 2], [18, 2], [-2, 18], [2, 18],
            // Maximum density within street boundaries (avoiding center)
            [-12, -6], [12, -6], [-12, 6], [12, 6],
            [-16, -4], [16, -4], [-16, 4], [16, 4],
            [-14, -6], [14, -6], [-14, 6], [14, 6],
            [-18, -14], [18, -14], [-14, -18], [14, -18],
            [-18, 14], [18, 14], [-14, 18], [14, 18],
            // Fill corners of blocks (avoiding center)
            [-10, -2], [10, -2], [-10, 2], [10, 2],
            [-8, -2], [8, -2], [-8, 2], [8, 2],
            [-12, -4], [12, -4], [-12, 4], [12, 4],
            // Additional dense positions
            [-18, -8], [18, -8], [-8, -18], [8, -18],
            [-18, 8], [18, 8], [-8, 18], [8, 18],
            [-16, -6], [16, -6], [-16, 6], [16, 6],
            [-14, -8], [14, -8], [-8, -14], [8, -14],
            [-14, 8], [14, 8], [-8, 14], [8, 14],
            [-10, -4], [10, -4], [-10, 4], [10, 4],
            [-12, -2], [12, -2], [-12, 2], [12, 2],
            // Final density within boundaries (avoiding center)
            [-16, -2], [16, -2], [-16, 2], [16, 2],
            [-14, -4], [14, -4], [-14, 4], [14, 4],
            [-18, -4], [18, -4], [-18, 4], [18, 4]
        ];
        
        for (let i = 0; i < count && this.addedHouses.length < emptySpots.length; i++) {
            const pos = emptySpots[this.addedHouses.length];
            const house = this.createHouse(pos[0], pos[1], this.houses.length + this.addedHouses.length);
            
            // Apply current investment scale to new house
            const intensity = this.redirectionRate;
            const scale = 1.0 + (intensity * 0.15); // Subtle scaling
            house.group.scale.set(scale, scale, scale);
            
            this.addedHouses.push({ house, position: pos });
            
            // Add money streams for new houses
            const randomCorp = this.corporateBuildings[Math.floor(Math.random() * this.corporateBuildings.length)];
            const corpStream = this.createMoneyStream(
                { x: pos[0], z: pos[1] },
                randomCorp.position,
                0x2ecc71
            );
            this.moneyStreams.push(corpStream);
            
            // Add local stream too
            const nearestStore = this.localStores[this.houses.length % this.localStores.length];
            const localStream = this.createMoneyStream(
                { x: pos[0], z: pos[1] },
                nearestStore.position,
                0x2ecc71,
                true
            );
            this.moneyStreams.push(localStream);
            
            // Add to main houses array for money tracking
            this.houses.push({ group: house.group, position: { x: pos[0], z: pos[1] }, moneyGeneration: Math.random() * 0.5 + 0.3 });
        }
    }
    

    
    updateBuildingScales() {
        // Scale buildings based on cumulative neighborhood investment
        const maxScaleInvestment = 10000000; // $10M for max building scaling
        const investmentProgress = Math.min(this.neighborhoodMoney / maxScaleInvestment, 1.0);
        
        // Subtle scale factor: 1.0 (no investment) to 1.15 (full investment)
        const baseScale = 1.0;
        const maxGrowth = 0.15; // Much more subtle growth
        const scale = baseScale + (investmentProgress * maxGrowth);
        
        // Scale original houses
        this.houses.forEach(house => {
            if (house.group) {
                house.group.scale.set(scale, scale, scale);
            }
        });
        
        // Scale local stores (they grow slightly more since they receive direct investment)
        this.localStores.forEach(store => {
            const storeScale = baseScale + (investmentProgress * 0.20); // 20% max growth for stores
            store.group.scale.set(storeScale, storeScale, storeScale);
        });
        
        // Scale newly added houses from flourishing
        this.addedHouses.forEach(houseData => {
            if (houseData.house && houseData.house.group) {
                houseData.house.group.scale.set(scale, scale, scale);
            }
        });
        
        // Scale park elements (benches, basketball court, sculptures)
        this.addedParks.forEach(parkData => {
            if (parkData.element) {
                const parkScale = baseScale + (investmentProgress * 0.10); // 10% max growth for park elements
                parkData.element.scale.set(parkScale, parkScale, parkScale);
            }
        });
        
        // Scale new businesses (they benefit most from local investment)
        this.addedBusinesses.forEach(businessData => {
            if (businessData.business && businessData.business.group) {
                const businessScale = baseScale + (investmentProgress * 0.25); // 25% max growth for businesses
                businessData.business.group.scale.set(businessScale, businessScale, businessScale);
            }
        });
        
        // Scale community spaces
        this.addedCommunitySpaces.forEach(spaceData => {
            if (spaceData.element) {
                const spaceScale = baseScale + (investmentProgress * 0.15); // 15% max growth for community spaces
                spaceData.element.scale.set(spaceScale, spaceScale, spaceScale);
            }
        });
    }
    
    updateGrassHealth() {
        if (!this.ground) return;
        
        // Transition from muted olive grass to royal healthy grass green
        const unhealthyColor = { r: 141, g: 179, b: 96 };  // Muted olive starting grass
        const healthyColor = { r: 34, g: 139, b: 34 };     // Royal healthy grass green
        
        // Base health on both current flow (40%) and cumulative investment (60%) - favor investment more
        const currentFlowIntensity = this.redirectionRate;
        const maxInvestmentForGrass = 3000000; // $3M for max grass health - much sooner!
        const investmentIntensity = Math.min(this.neighborhoodMoney / maxInvestmentForGrass, 1.0);
        const combinedIntensity = (currentFlowIntensity * 0.4) + (investmentIntensity * 0.6);
        
        const r = Math.round(unhealthyColor.r + (healthyColor.r - unhealthyColor.r) * combinedIntensity);
        const g = Math.round(unhealthyColor.g + (healthyColor.g - unhealthyColor.g) * combinedIntensity);
        const b = Math.round(unhealthyColor.b + (healthyColor.b - unhealthyColor.b) * combinedIntensity);
        
        // Convert to hex and update ground color
        const newColor = (r << 16) | (g << 8) | b;
        this.ground.material.color.setHex(newColor);
    }
    
    updateNeighborhoodFlourishing() {
        // Base flourishing on cumulative neighborhood investment with $10M max
        const maxFlourishMoney = 10000000; // $10 million for full flourishing
        const flourishingProgress = Math.min(this.neighborhoodMoney / maxFlourishMoney, 1.0);
        const targetLevel = Math.floor(flourishingProgress * 4); // 0-4 levels based on total money
        
        if (targetLevel > this.flourishingLevel) {
            // Add flourishing elements progressively - focus on businesses, parks, and community!
            if (this.flourishingLevel === 0 && targetLevel >= 1) {
                // Level 1: $2.5M+ invested - Basic neighborhood growth
                this.addNewHouses(12); // Fewer houses
                this.addNewBusinesses(3); // New local businesses!
                this.addFlourishingTrees(15);
                this.addFlowers(18);
            }
            if (this.flourishingLevel <= 1 && targetLevel >= 2) {
                // Level 2: $5M+ invested - Community spaces emerge
                this.addNewHouses(8); // Even fewer houses
                this.addNewBusinesses(4); // More businesses
                this.addPublicPark(); // West Park with trees, benches, flowers, sculpture
                this.addFlowers(24);
                this.addFlourishingTrees(9);
            }
            if (this.flourishingLevel <= 2 && targetLevel >= 3) {
                // Level 3: $7.5M+ invested - Recreation and culture
                this.addNewHouses(6); // Minimal new housing
                this.addNewBusinesses(3); // Cultural businesses
                this.addPublicPark(); // East Park with trees, benches, flowers, basketball court
                this.addCommunityGarden(); // Community garden!
                this.addFlourishingTrees(12);
                this.addFlowers(30);
            }
            if (this.flourishingLevel <= 3 && targetLevel >= 4) {
                // Level 4: $10M+ invested - Full community flourishing!
                this.addNewHouses(4); // Very few new houses
                this.addNewBusinesses(5); // Premium businesses
                this.addPublicPlaza(); // Central community plaza
                this.addFlourishingTrees(24);
                this.addFlowers(36);
                this.addParkElements(8, true, 8); // More varied park elements
            }
            
            this.flourishingLevel = targetLevel;
        }
        // Note: Flourishing doesn't go backwards since it's based on cumulative investment
        
        // Update grass health based on current money flow rate AND total investment
        this.updateGrassHealth();
    }
    
    advanceMonth() {
        this.currentMonth++;
        if (this.currentMonth > 12) {
            this.currentMonth = 1;
            this.currentYear++;
        }
    }
    
    updateTimeDisplay() {
        if (this.currentTimeSpan) {
            const monthName = this.monthNames[this.currentMonth - 1];
            this.currentTimeSpan.textContent = `${monthName} ${this.currentYear}`;
        }
    }
    
    updateMoneyDisplay() {
        // Format money amounts for display (no K shortening)
        const formatMoney = (amount) => {
            if (amount >= 1000000) {
                return '$' + (amount / 1000000).toFixed(1) + 'M';
            } else {
                return '$' + Math.round(amount).toLocaleString();
            }
        };
        
        this.moneyOutSpan.textContent = formatMoney(this.corporateMoney);
        this.moneyInSpan.textContent = formatMoney(this.neighborhoodMoney);
    }
    
    updateRedirection() {
        // Update money flow visualization - now showing cumulative amounts
        this.updateMoneyDisplay();
        
        // Scale all buildings based on neighborhood investment
        this.updateBuildingScales();
        
        // Add flourishing effects when money comes into neighborhood
        this.updateNeighborhoodFlourishing();
        
        // Visual effects are now handled by updateStreamVisibility
    }
    
    createLocalStreams() {
        // Create local streams for ALL houses to match corporate streams
        this.houses.forEach((house, index) => {
            const nearestStore = this.localStores[index % this.localStores.length];
            const localStream = this.createMoneyStream(
                house.position,
                nearestStore.position,
                0x2ecc71, // Green for money staying local
                true // Mark as local stream
            );
            this.moneyStreams.push(localStream);
        });
    }
    
    clearLocalStreams() {
        // Remove local streams, keep only corporate streams
        this.moneyStreams = this.moneyStreams.filter(stream => {
            if (stream.isLocal) { // Local streams
                // Remove particles from scene
                stream.particles.forEach(particle => {
                    this.scene.remove(particle);
                });
                return false; // Remove from array
            }
            return true; // Keep corporate streams
        });
    }
    
    updateStreamVisibility() {
        // Group streams by house to ensure 1:1 replacement
        const corporateStreams = this.moneyStreams.filter(s => !s.isLocal);
        const localStreams = this.moneyStreams.filter(s => s.isLocal);
        
        const totalHouses = this.houses.length;
        const localCount = Math.floor(totalHouses * this.redirectionRate);
        
        // Show corporate streams for houses that aren't redirected
        corporateStreams.forEach((stream, index) => {
            const shouldShow = index >= localCount;
            stream.particles.forEach(particle => {
                particle.visible = shouldShow;
            });
        });
        
        // Show local streams for houses that are redirected
        localStreams.forEach((stream, index) => {
            const shouldShow = index < localCount;
            stream.particles.forEach(particle => {
                particle.visible = shouldShow;
            });
        });
    }
    
    animate() {
        requestAnimationFrame(() => this.animate());
        
        this.updateMoneyStreams();
        this.updateMoneyAccumulation();
        
        // Fixed camera position - no rotation
        this.renderer.render(this.scene, this.camera);
    }
    
    onWindowResize() {
        this.camera.aspect = this.container.offsetWidth / this.container.offsetHeight;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(this.container.offsetWidth, this.container.offsetHeight);
    }
}

// Initialize the visualization when the page loads
document.addEventListener('DOMContentLoaded', () => {
    new NeighborhoodVisualization();
});
</script>