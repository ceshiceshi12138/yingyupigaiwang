// ==================== 全局变量 ====================
const humanAvatar = document.getElementById('humanAvatar');
const humanStatus = document.getElementById('humanStatus');
let progressChartInstance = null;
let currentTopic = '';
let currentVersions = [];
let userGrammarErrors = {};

// 话题库现在从 topics-data.js 加载
let displayedTopics = { beginner: [], intermediate: [], advanced: [] };

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', () => {
    humanStatus.textContent = '您好，我是小梦，有什么英语问题想问我吗？';
    initTopics();
    initKnowledgeGraph();
    loadGrammarStats();
    setupRealTimeGrammarCheck();
    loadProgressTopics();
    loadProgressChart();  // 页面加载时初始化图表
    
    // 导航栏交互
    const navToggle = document.querySelector('.nav-toggle');
    const navMenu = document.querySelector('.nav-menu');
    const navLinks = document.querySelectorAll('.nav-link');

    navToggle.addEventListener('click', () => {
        navMenu.classList.toggle('active');
    });

    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            navMenu.classList.remove('active');
        });
    });

    // 快捷问题按钮
    document.querySelectorAll('.quick-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const question = btn.getAttribute('data-question');
            document.getElementById('qaInput').value = question;
            sendQuestion();
        });
    });

    // 字数统计
    const essayContent = document.getElementById('essayContent');
    essayContent.addEventListener('input', () => {
        const count = essayContent.value.trim().length;
        document.getElementById('wordCount').textContent = count;
    });
});

// ==================== 数字人控制 ====================
function setHumanSpeaking(speaking) {
    if (speaking) {
        humanAvatar.classList.add('speaking');
        humanStatus.textContent = '思考中...';
    } else {
        humanAvatar.classList.remove('speaking');
    }
}

// ==================== 话题推荐 ====================
function initTopics() {
    refreshTopics();
}

function refreshTopics() {
    const topicsGrid = document.getElementById('topicsGrid');
    if (!topicsGrid) return;

    const beginnerTopics = getRandomTopics('beginner', 6);
    const intermediateTopics = getRandomTopics('intermediate', 6);
    const advancedTopics = getRandomTopics('advanced', 6);

    topicsGrid.innerHTML = `
        <div class="topic-category">
            <h3>初级话题</h3>
            <div class="topic-list">
                ${beginnerTopics.map(t => createTopicButton(t)).join('')}
            </div>
        </div>
        <div class="topic-category">
            <h3>中级话题</h3>
            <div class="topic-list">
                ${intermediateTopics.map(t => createTopicButton(t)).join('')}
            </div>
        </div>
        <div class="topic-category">
            <h3>高级话题</h3>
            <div class="topic-list">
                ${advancedTopics.map(t => createTopicButton(t)).join('')}
            </div>
        </div>
    `;

    bindTopicEvents();
}

function getRandomTopics(level, count) {
    const library = topicsLibrary[level];
    const displayed = displayedTopics[level];
    
    let available = library.filter(t => !displayed.includes(t.title));
    
    if (available.length < count) {
        displayedTopics[level] = [];
        available = library;
    }
    
    const selected = [];
    const tempAvailable = [...available];
    
    for (let i = 0; i < count && tempAvailable.length > 0; i++) {
        const randomIndex = Math.floor(Math.random() * tempAvailable.length);
        selected.push(tempAvailable[randomIndex]);
        displayedTopics[level].push(tempAvailable[randomIndex].title);
        tempAvailable.splice(randomIndex, 1);
    }
    
    return selected;
}

function createTopicButton(topic) {
    return `<button class="topic-btn" data-topic="${topic.title}">${topic.title} (${topic.desc})</button>`;
}

function bindTopicEvents() {
    document.querySelectorAll('.topic-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const topic = btn.getAttribute('data-topic');
            document.getElementById('essayTopic').value = topic;
            document.getElementById('essayTitle').value = topic;
            document.getElementById('essayContent').focus();
            scrollToSection('correct');
        });
    });
}

// ==================== 平滑滚动 ====================
function scrollToSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (section) {
        section.scrollIntoView({ behavior: 'smooth' });
    }
}

// ==================== 作文批改 ====================
function clearEssay() {
    document.getElementById('essayTopic').value = '';
    document.getElementById('essayTitle').value = '';
    document.getElementById('essayContent').value = '';
    document.getElementById('wordCount').textContent = '0';
    document.getElementById('correctionResult').style.display = 'none';
}

async function submitEssay() {
    const topic = document.getElementById('essayTopic').value.trim();
    const title = document.getElementById('essayTitle').value.trim();
    const content = document.getElementById('essayContent').value.trim();
    const submitBtn = document.getElementById('submitBtn');
    const btnText = submitBtn.querySelector('.btn-text');
    const btnLoading = submitBtn.querySelector('.btn-loading');

    if (!content || content.length < 10) {
        alert('请输入足够的作文内容（至少10个字符）');
        return;
    }

    currentTopic = topic || title || '未分类';

    btnText.style.display = 'none';
    btnLoading.style.display = 'inline-block';
    submitBtn.disabled = true;

    const resultSection = document.getElementById('correctionResult');
    resultSection.style.display = 'block';

    humanStatus.textContent = '小梦正在批改作文...';
    setHumanSpeaking(true);

    try {
        const response = await fetch('/api/correct', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                essay: content,
                title: title,
                topic: currentTopic
            })
        });

        const data = await response.json();

        if (data.success) {
            displayFourDimensionScores(data.scores);
            displayErrors(data.grammar_errors || []);
            displaySummary(data.response);
            loadGrammarStats();
    loadProgressTopics();
    loadProgressChart();  // 初始加载图表数据
            
            if (data.version_info) {
                showNotification(`已保存为版本 ${data.version_info.version_number}`);
            }
        } else {
            document.getElementById('errorList').innerHTML = 
                `<div class="qa-empty" style="color: #FF6B6B;">批改失败: ${data.error || '未知错误'}</div>`;
        }
    } catch (error) {
        document.getElementById('errorList').innerHTML = 
            `<div class="qa-empty" style="color: #FF6B6B;">网络错误，请稍后重试</div>`;
    } finally {
        btnText.style.display = 'inline-block';
        btnLoading.style.display = 'none';
        submitBtn.disabled = false;
        setHumanSpeaking(false);
        humanStatus.textContent = '批改完成';
    }
}

// ==================== 四维评分展示 ====================
function displayFourDimensionScores(scores) {
    const langBase = scores.language_base || { grammar: 8, vocabulary: 8, total: 16 };
    const contentIdea = scores.content_idea || { completeness: 8, coherence: 8, depth: 7, total: 23 };
    const structure = scores.structure || { organization: 8, transition: 8, total: 16 };
    const writingNorm = scores.writing_norm || { format: 8, total: 8 };
    const total = scores.total || 63;

    // 语言基础
    document.getElementById('langBaseTotal').textContent = `${langBase.total}/35`;
    document.getElementById('grammarScore').textContent = `${langBase.grammar}/17.5`;
    document.getElementById('vocabScore').textContent = `${langBase.vocabulary}/17.5`;
    document.getElementById('grammarBar').style.width = `${(langBase.grammar / 17.5) * 100}%`;
    document.getElementById('vocabBar').style.width = `${(langBase.vocabulary / 17.5) * 100}%`;

    // 内容思想
    document.getElementById('contentTotal').textContent = `${contentIdea.total}/35`;
    document.getElementById('completeScore').textContent = `${contentIdea.completeness}/12`;
    document.getElementById('logicScore').textContent = `${contentIdea.coherence}/12`;
    document.getElementById('depthScore').textContent = `${contentIdea.depth}/11`;
    document.getElementById('completeBar').style.width = `${(contentIdea.completeness / 12) * 100}%`;
    document.getElementById('logicBar').style.width = `${(contentIdea.coherence / 12) * 100}%`;
    document.getElementById('depthBar').style.width = `${(contentIdea.depth / 11) * 100}%`;

    // 结构形式
    document.getElementById('structureTotal').textContent = `${structure.total}/20`;
    document.getElementById('orgScore').textContent = `${structure.organization}/10`;
    document.getElementById('transScore').textContent = `${structure.transition}/10`;
    document.getElementById('orgBar').style.width = `${(structure.organization / 10) * 100}%`;
    document.getElementById('transBar').style.width = `${(structure.transition / 10) * 100}%`;

    // 写作规范
    document.getElementById('normTotal').textContent = `${writingNorm.total}/10`;
    document.getElementById('formatScore').textContent = `${writingNorm.format}/10`;
    document.getElementById('formatBar').style.width = `${(writingNorm.format / 10) * 100}%`;

    // 总分
    document.getElementById('finalScore').textContent = total;
}

function displayErrors(errors) {
    const errorList = document.getElementById('errorList');
    
    if (!errors || errors.length === 0) {
        errorList.innerHTML = '<div class="empty-hint">恭喜！未发现明显错误</div>';
        return;
    }

    errorList.innerHTML = errors.map(err => `
        <div class="error-item">
            <div class="original">❌ ${err.original}</div>
            <div class="corrected">✓ ${err.corrected}</div>
            <div class="reason">📝 ${err.reason || '语法或用词错误'}</div>
        </div>
    `).join('');
}

function displaySummary(response) {
    const summaryContent = document.getElementById('summaryContent');
    // 提取评价和建议部分
    const parts = response.split(/【总体评价】|【改进建议】/);
    let summary = response;
    if (parts.length >= 2) {
        summary = parts.slice(1).join('<br><br>');
    }
    summaryContent.innerHTML = formatResponse(summary);
}

function formatResponse(text) {
    return text.replace(/\n/g, '<br>').replace(/\*\*/g, '');
}

// ==================== 知识图谱 ====================
let knowledgeGraphData = null;
let selectedCategoryNode = null; // 当前选中的三级节点

async function initKnowledgeGraph() {
    try {
        const response = await fetch('/api/knowledge/graph');
        const data = await response.json();
        
        if (data.success) {
            knowledgeGraphData = data.graph;
            renderKnowledgeGraph();
        }
    } catch (error) {
        console.error('加载知识图谱失败:', error);
    }
}

function renderKnowledgeGraph() {
    const svg = document.getElementById('knowledgeGraphSvg');
    if (!svg || !knowledgeGraphData) return;

    const width = 1000;
    const height = 700;
    const centerX = width / 2;
    const centerY = height / 2;
    
    // 中心辐射式布局：4层结构
    const nodePositions = {};
    
    // 定义层级半径 - 四级节点使用动态半径
    const radius = {
        1: 0,      // 中心节点
        2: 110,    // 文体层
        3: 200,    // 分类层
        4: 290     // 内容层基准半径（实际会在此基础上偏移）
    };
    
    // 按层级和类型分组
    const centerNode = knowledgeGraphData.nodes.find(n => n.level === 1);
    const genreNodes = knowledgeGraphData.nodes.filter(n => n.type === 'genre');
    const categoryNodes = knowledgeGraphData.nodes.filter(n => n.type === 'category');
    const contentNodes = knowledgeGraphData.nodes.filter(n => n.type === 'content');
    
    // Level 1: 中心节点
    if (centerNode) {
        nodePositions[centerNode.id] = {
            x: centerX,
            y: centerY,
            ...centerNode
        };
    }
    
    // Level 2: 文体节点 - 均匀分布在圆周上
    const genreAngles = {};
    genreNodes.forEach((node, i) => {
        const angle = (i / genreNodes.length) * 2 * Math.PI - Math.PI / 2;
        genreAngles[node.id] = angle;
        nodePositions[node.id] = {
            x: centerX + Math.cos(angle) * radius[2],
            y: centerY + Math.sin(angle) * radius[2],
            ...node
        };
    });
    
    // Level 3: 分类节点 - 围绕各自的文体节点分布
    const genreToCategories = {};
    categoryNodes.forEach(node => {
        if (!genreToCategories[node.parent]) genreToCategories[node.parent] = [];
        genreToCategories[node.parent].push(node);
    });

    Object.entries(genreToCategories).forEach(([genreId, categories]) => {
        const genreAngle = genreAngles[genreId];
        const genrePos = nodePositions[genreId];
        // 修复：使用严格判断，角度为0是有效值
        if (genreAngle === undefined || genreAngle === null || !genrePos) {
            console.warn('Missing genre data:', genreId, genreAngle, genrePos);
            return;
        }

        // 增大扇形区域到60度，让分类节点分布更分散
        const spreadAngle = Math.PI / 3;
        categories.forEach((node, i) => {
            const count = categories.length;
            let angleOffset;
            if (count === 1) {
                angleOffset = 0;
            } else {
                angleOffset = (i - (count - 1) / 2) * (spreadAngle / (count - 1));
            }
            const angle = genreAngle + angleOffset;
            nodePositions[node.id] = {
                x: centerX + Math.cos(angle) * radius[3],
                y: centerY + Math.sin(angle) * radius[3],
                ...node
            };
        });
    });
    
    // Level 4: 内容节点 - 围绕各自的分类节点切线方向分布，避免交叉
    const categoryToContents = {};
    contentNodes.forEach(node => {
        if (!categoryToContents[node.parent]) categoryToContents[node.parent] = [];
        categoryToContents[node.parent].push(node);
    });

    // 为每个分类分配不同的半径偏移，形成分层结构避免交叉
    const categoryIds = Object.keys(categoryToContents);
    const radiusOffsets = {};
    categoryIds.forEach((catId, idx) => {
        // 根据分类索引分配不同的半径偏移（-30, -10, +10, +30, -20, +20...）
        const pattern = [-30, -10, 10, 30, -20, 20, 0, -15, 15, 25, -25];
        radiusOffsets[catId] = pattern[idx % pattern.length];
    });

    // 记录哪些四级节点需要显示
    const visibleContentIds = new Set();
    
    Object.entries(categoryToContents).forEach(([categoryId, contents]) => {
        // 只有选中的三级节点才显示其四级子节点
        const shouldShow = selectedCategoryNode === categoryId;
        
        if (shouldShow) {
            const categoryPos = nodePositions[categoryId];
            if (!categoryPos) {
                console.warn('Category position not found:', categoryId);
                return;
            }

            // 计算从中心到分类节点的角度
            const categoryAngle = Math.atan2(categoryPos.y - centerY, categoryPos.x - centerX);
            const spreadAngle = Math.PI / 3; // 60度扇形

            // 为该分类计算专属半径
            const categoryRadius = radius[4] + (radiusOffsets[categoryId] || 0);

            contents.forEach((node, i) => {
                const count = contents.length;
                let angleOffset;
                if (count === 1) {
                    angleOffset = 0;
                } else {
                    angleOffset = (i - (count - 1) / 2) * (spreadAngle / (count - 1));
                }

                // 在切线方向上偏移角度，但保持大致向外的趋势
                const finalAngle = categoryAngle + angleOffset * 0.5;
                const finalRadius = categoryRadius + Math.abs(angleOffset) * 30;

                nodePositions[node.id] = {
                    x: centerX + Math.cos(finalAngle) * finalRadius,
                    y: centerY + Math.sin(finalAngle) * finalRadius,
                    ...node
                };
                
                visibleContentIds.add(node.id);
            });
        }
    });

    // 调试用：输出节点位置统计
    console.log('Knowledge Graph Nodes:', {
        center: Object.values(nodePositions).filter(n => n.level === 1).length,
        genre: Object.values(nodePositions).filter(n => n.level === 2).length,
        category: Object.values(nodePositions).filter(n => n.level === 3).length,
        content: Object.values(nodePositions).filter(n => n.level === 4).length
    });

    // 绘制连线
    let svgContent = `
        <defs>
            <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
                <feMerge>
                    <feMergeNode in="coloredBlur"/>
                    <feMergeNode in="SourceGraphic"/>
                </feMerge>
            </filter>
        </defs>
    `;
    
    // 绘制连接线 - 只绘制可见的连接
    knowledgeGraphData.links.forEach(link => {
        const source = nodePositions[link.source];
        const target = nodePositions[link.target];
        if (source && target) {
            // 如果是四级节点的连线，只有当目标节点可见时才绘制
            if (target.level === 4 && !visibleContentIds.has(link.target)) {
                return;
            }
            
            // 根据连接类型设置样式
            let strokeStyle = '';
            let strokeColor = '';
            let strokeWidth = 2;

            if (link.type === 'solid') {
                strokeStyle = '';
                strokeColor = source.color || '#ffffff';
                strokeWidth = target.level === 4 ? 2.5 : 2;
            } else if (link.type === 'dashed') {
                strokeStyle = 'stroke-dasharray="5,5"';
                strokeColor = source.color || '#ffffff';
                strokeWidth = 2;
            }

            // 计算连线透明度：提高可见度
            const opacity = Math.max(0.5, 0.9 - (target.level - 1) * 0.1);

            svgContent += `<line class="graph-link" x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}"
                stroke="${strokeColor}" stroke-width="${strokeWidth}" opacity="${opacity}" ${strokeStyle} />`;
        }
    });

    // 节点尺寸映射
    const sizes = {
        1: 70,   // 中心节点
        2: 50,   // 文体
        3: 36,   // 分类
        4: 28    // 内容 - 稍微缩小避免重叠
    };

    // 绘制节点
    Object.values(nodePositions).forEach(node => {
        // 四级节点只有在可见时才绘制
        if (node.level === 4 && !visibleContentIds.has(node.id)) {
            return;
        }
        
        const size = sizes[node.level] || 30;
        const color = node.color || '#95E1D3';

        // 节点发光效果（中心节点和文体节点）
        const filter = node.level <= 2 ? 'filter="url(#glow)"' : '';

        // 文本内容完整显示
        let displayText = node.name;

        // 字体大小调整
        const fontSize = node.level === 1 ? 14 : (node.level === 2 ? 13 : 11);
        
        // 判断是否是选中的三级节点
        const isSelectedCategory = node.type === 'category' && selectedCategoryNode === node.id;
        const strokeWidth = isSelectedCategory ? 5 : 3;
        const strokeColor = isSelectedCategory ? '#FFD700' : '#fff';
        
        // 节点阴影
        svgContent += `
            <g class="graph-node ${node.type === 'category' ? 'category-node' : ''}" data-id="${node.id}" onclick="handleNodeClick('${node.id}', '${node.type}')" style="cursor: pointer;">
                <circle cx="${node.x}" cy="${node.y}" r="${size + 4}" 
                        fill="rgba(0,0,0,0.3)" opacity="0.5" />
                <circle cx="${node.x}" cy="${node.y}" r="${size}" 
                        fill="${color}" stroke="${strokeColor}" stroke-width="${strokeWidth}" ${filter} />
                <text x="${node.x}" y="${node.y + 4}" text-anchor="middle" 
                      fill="white" font-size="${fontSize}" font-weight="bold" style="pointer-events: none;">
                    ${displayText}
                </text>
            </g>
        `;
    });

    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.innerHTML = svgContent;
}

// 处理节点点击事件
function handleNodeClick(nodeId, nodeType) {
    if (nodeType === 'category') {
        // 三级节点：切换展开/收起状态
        if (selectedCategoryNode === nodeId) {
            // 如果点击的是已选中的节点，则收起
            selectedCategoryNode = null;
        } else {
            // 否则切换到新的节点
            selectedCategoryNode = nodeId;
        }
        // 重新渲染图谱
        renderKnowledgeGraph();
    }
    // 显示节点详情
    showNodeDetails(nodeId);
}

function showNodeDetails(nodeId) {
    const details = document.getElementById('knowledgeDetails');
    const nodeData = knowledgeGraphData.details[nodeId];
    const node = knowledgeGraphData.nodes.find(n => n.id === nodeId);
    
    if (!nodeData) {
        details.innerHTML = `<div class="empty-hint">点击图谱节点查看中学英语作文的各类知识要点</div>`;
        return;
    }

    let html = '';
    
    // 标题
    if (nodeData.title) {
        html += `<h4>${nodeData.title}</h4>`;
    } else if (node) {
        html += `<h4>${node.name}</h4>`;
    }
    
    // 描述
    if (nodeData.description) {
        html += `<p>${nodeData.description}</p>`;
    }
    
    // 特点
    if (nodeData.features) {
        html += `<h5>主要特点</h5><ul>`;
        nodeData.features.forEach(feature => {
            html += `<li>${feature}</li>`;
        });
        html += `</ul>`;
    }
    
    // 例句/例子
    if (nodeData.examples) {
        html += `<h5>常用表达</h5><ul>`;
        nodeData.examples.forEach(ex => {
            html += `<li><em>"${ex}"</em></li>`;
        });
        html += `</ul>`;
    }
    
    // 要点/结构
    if (nodeData.points) {
        html += `<h5>要点说明</h5><ul>`;
        nodeData.points.forEach(point => {
            html += `<li>${point}</li>`;
        });
        html += `</ul>`;
    }
    
    // 写作技巧
    if (nodeData.tips) {
        html += `<h5>写作技巧</h5><ul>`;
        nodeData.tips.forEach(tip => {
            html += `<li>${tip}</li>`;
        });
        html += `</ul>`;
    }
    
    details.innerHTML = html;
}

// ==================== 版本管理 ====================
async function showVersions() {
    const topic = document.getElementById('essayTopic').value.trim() || currentTopic;
    
    try {
        const url = topic ? `/api/versions?topic=${encodeURIComponent(topic)}` : '/api/versions';
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.success) {
            currentVersions = data.versions;
            renderVersionList(data.versions);
            openModal('versionModal');
        }
    } catch (error) {
        showNotification('加载版本历史失败', 'error');
    }
}

function renderVersionList(versions) {
    const list = document.getElementById('versionList');
    
    if (versions.length === 0) {
        list.innerHTML = '<div class="empty-hint">暂无历史版本</div>';
        return;
    }
    
    list.innerHTML = versions.map((v, index) => `
        <div class="version-item">
            <div class="version-info">
                <div class="version-topic">${v.topic}</div>
                <div class="version-meta">版本 ${v.version_number} · ${new Date(v.created_at).toLocaleDateString()}</div>
            </div>
            <div class="version-score">${v.total_score}分</div>
            <div class="version-actions">
                ${index < versions.length - 1 ? `<button class="version-btn" onclick="compareVersions('${v.id}', '${versions[index + 1].id}')">对比</button>` : ''}
            </div>
        </div>
    `).join('');
}

async function loadVersion(versionId) {
    try {
        const response = await fetch(`/api/versions`);
        const data = await response.json();
        
        if (data.success) {
            const version = data.versions.find(v => v.id === versionId);
            if (version) {
                // 需要额外请求获取完整内容
                showNotification('功能开发中：加载版本');
            }
        }
    } catch (error) {
        showNotification('加载版本失败', 'error');
    }
}

async function compareVersions(v1, v2) {
    try {
        const response = await fetch('/api/versions/compare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ version_id1: v1, version_id2: v2 })
        });
        
        const data = await response.json();
        
        if (data.success) {
            document.getElementById('compareV1').textContent = data.version1.version_number;
            document.getElementById('compareV2').textContent = data.version2.version_number;
            document.getElementById('compareS1').textContent = data.version1.total_score;
            document.getElementById('compareS2').textContent = data.version2.total_score;
            document.getElementById('compareContent1').textContent = data.version1.content;
            document.getElementById('compareContent2').textContent = data.version2.content;
            
            closeModal('versionModal');
            openModal('compareModal');
        }
    } catch (error) {
        showNotification('对比失败', 'error');
    }
}

async function loadLastVersion() {
    const topic = document.getElementById('essayTopic').value.trim();
    if (!topic) {
        showNotification('请先输入话题', 'warning');
        return;
    }
    
    try {
        const response = await fetch(`/api/versions?topic=${encodeURIComponent(topic)}`);
        const data = await response.json();
        
        if (data.success && data.versions.length > 0) {
            const lastVersion = data.versions[0];
            showNotification(`已加载版本 ${lastVersion.version_number}，得分: ${lastVersion.total_score}`);
        } else {
            showNotification('该话题暂无历史版本');
        }
    } catch (error) {
        showNotification('加载失败', 'error');
    }
}

// ==================== 进步追踪（折线图）====================
async function loadProgressTopics() {
    try {
        const response = await fetch('/api/versions');
        const data = await response.json();
        
        if (data.success) {
            // 获取所有话题，并标准化（使用第一个出现的大小写格式作为标准）
            const topicMap = new Map();
            data.versions.forEach(v => {
                const lowerTopic = v.topic.toLowerCase();
                if (!topicMap.has(lowerTopic)) {
                    topicMap.set(lowerTopic, v.topic);
                }
            });
            
            const topics = Array.from(topicMap.values());
            const select = document.getElementById('progressTopicSelect');
            select.innerHTML = '<option value="">全部话题</option>' + 
                topics.map(t => `<option value="${t}">${t}</option>`).join('');
        }
    } catch (error) {
        console.error('加载话题列表失败:', error);
    }
}

async function loadProgressChart() {
    const topicSelect = document.getElementById('progressTopicSelect');
    const dimensionSelect = document.getElementById('progressDimensionSelect');

    if (!topicSelect || !dimensionSelect) {
        console.error('选择器元素未找到');
        return;
    }

    const topic = topicSelect.value;
    const dimension = dimensionSelect.value;

    console.log('加载图表数据:', { topic, dimension });

    try {
        const url = `/api/progress/chart${topic ? '?topic=' + encodeURIComponent(topic) : ''}`;
        console.log('请求URL:', url);

        const response = await fetch(url);
        const data = await response.json();

        console.log('API返回数据:', data);

        if (data.success) {
            renderProgressChart(data.data, dimension);
            updateProgressStats(data.data);
        } else {
            console.error('API返回错误:', data.error);
            renderProgressChart([], dimension);
            updateProgressStats([]);
        }
    } catch (error) {
        console.error('加载图表失败:', error);
        renderProgressChart([], dimension);
        updateProgressStats([]);
    }
}

function renderProgressChart(chartData, dimension) {
    const canvas = document.getElementById('progressChart');
    if (!canvas) {
        console.error('Canvas元素未找到');
        return;
    }
    
    const ctx = canvas.getContext('2d');
    
    if (progressChartInstance) {
        progressChartInstance.destroy();
    }
    
    // 如果没有数据，显示提示信息
    if (!chartData || chartData.length === 0) {
        // 清空canvas并显示提示文字
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.font = '16px Arial';
        ctx.fillStyle = '#999';
        ctx.textAlign = 'center';
        ctx.fillText('该话题暂无写作数据', canvas.width / 2, canvas.height / 2);
        return;
    }
    
    const labels = chartData.map(d => `V${d.version}`);
    const data = chartData.map(d => d[dimension] || d.total);
    
    const colors = {
        total: '#4A90E2',
        language_base: '#FF6B6B',
        content_idea: '#50C878',
        structure: '#FFA500',
        writing_norm: '#9b59b6'
    };
    
    const dimensionNames = {
        total: '总分',
        language_base: '语言基础',
        content_idea: '内容思想',
        structure: '结构形式',
        writing_norm: '写作规范'
    };
    
    progressChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: dimensionNames[dimension] || '得分',
                data: data,
                borderColor: colors[dimension] || '#4A90E2',
                backgroundColor: (colors[dimension] || '#4A90E2') + '20',
                fill: true,
                tension: 0.4,
                pointRadius: 5,
                pointHoverRadius: 7
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: dimension === 'total' ? 100 : 
                         dimension === 'language_base' || dimension === 'content_idea' ? 35 :
                         dimension === 'structure' ? 20 : 10
                }
            }
        }
    });
}

function updateProgressStats(chartData) {
    if (chartData.length === 0) {
        document.getElementById('statCount').textContent = '0';
        document.getElementById('statMax').textContent = '0';
        document.getElementById('statAvg').textContent = '0';
        document.getElementById('statImprove').textContent = '0';
        return;
    }
    
    const scores = chartData.map(d => d.total);
    const count = scores.length;
    const max = Math.max(...scores);
    const avg = (scores.reduce((a, b) => a + b, 0) / count).toFixed(1);
    const improve = (scores[scores.length - 1] - scores[0]).toFixed(1);
    
    document.getElementById('statCount').textContent = count;
    document.getElementById('statMax').textContent = max;
    document.getElementById('statAvg').textContent = avg;
    document.getElementById('statImprove').textContent = (improve > 0 ? '+' : '') + improve;
}

function showProgress() {
    scrollToSection('progress');
    loadProgressChart();
}

// ==================== 语法错误追踪 ====================
async function loadGrammarStats() {
    try {
        const response = await fetch('/api/grammar/errors');
        const data = await response.json();
        
        if (data.success) {
            renderGrammarStats(data.errors);
        }
    } catch (error) {
        console.error('加载语法统计失败:', error);
    }
}

function renderGrammarStats(errors) {
    const container = document.getElementById('grammarStatsList');
    
    if (errors.length === 0) {
        container.innerHTML = '<div class="empty-hint">暂无数据，开始写作后会自动统计</div>';
        return;
    }
    
    const typeNames = {
        tense: '时态错误',
        voice: '语态错误',
        sv_agreement: '主谓一致',
        article: '冠词使用',
        preposition: '介词搭配',
        collocation: '词汇搭配',
        vocabulary: '词汇错误',
        spelling: '拼写错误',
        punctuation: '标点符号',
        sentence_structure: '句式结构',
        grammar: '语法错误',
        capitalization: '大小写'
    };
    
    container.innerHTML = errors.slice(0, 5).map(err => `
        <div class="grammar-stat-item">
            <span class="grammar-stat-type">${typeNames[err.type] || err.type}</span>
            <span class="grammar-stat-count">${err.count}次</span>
        </div>
    `).join('');
}

// ==================== 实时语法检查 ====================
let grammarCheckTimeout;

function setupRealTimeGrammarCheck() {
    const textarea = document.getElementById('essayContent');
    
    textarea.addEventListener('input', () => {
        clearTimeout(grammarCheckTimeout);
        grammarCheckTimeout = setTimeout(checkGrammar, 1000);
    });
}

async function checkGrammar() {
    const text = document.getElementById('essayContent').value;
    if (text.length < 20) return;
    
    try {
        const response = await fetch('/api/grammar/hints', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        });
        
        const data = await response.json();
        
        if (data.success && data.hints.length > 0) {
            displayGrammarHints(data.hints);
        }
    } catch (error) {
        console.error('语法检查失败:', error);
    }
}

function displayGrammarHints(hints) {
    const container = document.getElementById('grammarHints');
    
    container.innerHTML = hints.map(hint => `
        <div class="grammar-bubble ${hint.severity}" 
             title="${hint.message}"
             onclick="showGrammarLesson('${hint.type}')">
            ${hint.type === 'tense' ? '⚠️ 时态' : 
              hint.type === 'article' ? '⚠️ 冠词' : 
              hint.type === 'preposition' ? '⚠️ 介词' : '⚠️ 语法'}
        </div>
    `).join('');
}

function showGrammarLesson(errorType) {
    const lessons = {
        tense: {
            title: '时态用法详解',
            content: `
                <h4>一般现在时 vs 一般过去时</h4>
                <div class="example">
                    <p class="wrong">I go to school yesterday.</p>
                    <p class="correct">I went to school yesterday.</p>
                </div>
                <h4>现在完成时用法</h4>
                <div class="example">
                    <p class="wrong">I have been to Beijing last year.</p>
                    <p class="correct">I went to Beijing last year.</p>
                </div>
            `,
            practice: '用正确的时态填空：I ______ (visit) my grandparents last weekend.'
        },
        article: {
            title: '冠词使用规则',
            content: `
                <h4>a/an 的用法</h4>
                <div class="example">
                    <p class="wrong">I am a university student.</p>
                    <p class="correct">I am a university student. ✓ (u发辅音)</p>
                </div>
                <h4>the 的用法</h4>
                <div class="example">
                    <p class="wrong">I like the music. (泛指)</p>
                    <p class="correct">I like music.</p>
                </div>
            `,
            practice: '填空：______ sun rises in ______ east.'
        }
    };
    
    const lesson = lessons[errorType] || lessons.tense;
    document.getElementById('grammarLesson').innerHTML = `
        <h4>${lesson.title}</h4>
        ${lesson.content}
        <h4>自测练习</h4>
        <p>${lesson.practice}</p>
    `;
    
    openModal('grammarPushModal');
}

// ==================== AI问答 ====================
function handleQAKeypress(event) {
    if (event.key === 'Enter') {
        sendQuestion();
    }
}

async function sendQuestion() {
    const input = document.getElementById('qaInput');
    const question = input.value.trim();

    if (!question) return;

    const qaHistory = document.getElementById('qaHistory');
    
    // 移除欢迎语
    const welcomeMsg = qaHistory.querySelector('.qa-welcome');
    if (welcomeMsg) welcomeMsg.remove();

    // 添加用户消息
    const userMsg = document.createElement('div');
    userMsg.className = 'qa-message user';
    userMsg.innerHTML = `<div class="role">👤 您</div><div class="content">${question}</div>`;
    qaHistory.appendChild(userMsg);

    input.value = '';

    // 添加助手消息占位符
    const assistantMsg = document.createElement('div');
    assistantMsg.className = 'qa-message assistant';
    assistantMsg.innerHTML = `<div class="role">🤖 小梦</div><div class="content">正在思考...</div>`;
    qaHistory.appendChild(assistantMsg);

    qaHistory.scrollTop = qaHistory.scrollHeight;
    humanStatus.textContent = '小梦正在思考...';
    setHumanSpeaking(true);

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: question })
        });

        const data = await response.json();

        if (data.success) {
            assistantMsg.querySelector('.content').innerHTML = formatResponse(data.response);
            humanStatus.textContent = '回答完成';
        } else {
            assistantMsg.querySelector('.content').innerHTML = '抱歉，发生了错误: ' + (data.error || '未知错误');
            humanStatus.textContent = '发生错误';
        }
    } catch (error) {
        assistantMsg.querySelector('.content').innerHTML = '网络错误，请稍后重试';
        humanStatus.textContent = '网络错误';
    } finally {
        setHumanSpeaking(false);
        qaHistory.scrollTop = qaHistory.scrollHeight;
    }
}

// ==================== 模态框 ====================
function openModal(modalId) {
    document.getElementById(modalId).style.display = 'flex';
}

function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

// 点击模态框外部关闭
window.onclick = function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.style.display = 'none';
    }
}

// ==================== 通知 ====================
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 80px;
        right: 20px;
        padding: 15px 20px;
        background: ${type === 'error' ? '#FF6B6B' : type === 'warning' ? '#FFA500' : '#4A90E2'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 3000;
        font-size: 14px;
        animation: slideIn 0.3s ease;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// 添加动画样式
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);
